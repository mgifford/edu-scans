"""URL validation service for checking government site accessibility."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx


@dataclass(slots=True)
class ValidationResult:
    """Result of a URL validation check."""
    url: str
    is_valid: bool
    status_code: int | None = None
    error_message: str | None = None
    redirected_to: str | None = None
    redirect_chain: List[str] | None = None
    validated_at: str | None = None


class UrlValidator:
    """Service for validating URL accessibility with redirect tracking."""

    def __init__(
        self,
        timeout_seconds: int = 20,
        max_redirects: int = 10,
        user_agent: str = "EU-Government-Accessibility-Scanner/1.0",
    ):
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.user_agent = user_agent

    async def validate_url(self, url: str) -> ValidationResult:
        """
        Validate a single URL and track redirects.

        Returns ValidationResult with success/failure status, error codes,
        and redirect information.
        """
        validated_at = datetime.now(timezone.utc).isoformat()

        # Track redirect chain
        redirect_chain: List[str] = []

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=self.max_redirects,
                timeout=self.timeout_seconds,
                event_hooks={
                    "response": [self._track_redirect(redirect_chain)]
                },
            ) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                )

                # Determine final URL after redirects
                final_url = str(response.url)
                redirected_to = final_url if final_url != url else None

                # Consider 2xx and 3xx as valid (3xx should have been followed)
                is_valid = response.status_code < 400

                return ValidationResult(
                    url=url,
                    is_valid=is_valid,
                    status_code=response.status_code,
                    redirected_to=redirected_to,
                    redirect_chain=redirect_chain if redirect_chain else None,
                    validated_at=validated_at,
                )

        except httpx.TooManyRedirects as e:
            return ValidationResult(
                url=url,
                is_valid=False,
                error_message=f"Too many redirects: {str(e)}",
                validated_at=validated_at,
            )
        except httpx.TimeoutException as e:
            return ValidationResult(
                url=url,
                is_valid=False,
                error_message=f"Timeout: {str(e)}",
                validated_at=validated_at,
            )
        except httpx.ConnectError as e:
            return ValidationResult(
                url=url,
                is_valid=False,
                error_message=f"Connection error: {str(e)}",
                validated_at=validated_at,
            )
        except httpx.HTTPError as e:
            return ValidationResult(
                url=url,
                is_valid=False,
                error_message=f"HTTP error: {str(e)}",
                validated_at=validated_at,
            )
        except Exception as e:
            return ValidationResult(
                url=url,
                is_valid=False,
                error_message=f"Unexpected error: {str(e)}",
                validated_at=validated_at,
            )

    def _track_redirect(self, redirect_chain: List[str]):
        """
        Create event hook to track redirect chain.

        Returns a callback function for use with httpx event hooks that
        appends intermediate redirect URLs to the redirect_chain list
        when responses have redirect status codes (3xx).

        Args:
            redirect_chain: List to accumulate redirect URLs

        Returns:
            Async event hook function that accepts an httpx Response
        """
        async def hook(response: httpx.Response):
            if response.is_redirect:
                redirect_chain.append(str(response.url))
        return hook

    async def validate_urls_batch(
        self,
        urls: List[str],
        rate_limit_per_second: float = 2.0,
        max_runtime_seconds: Optional[float] = None,
        start_time: Optional[float] = None,
        on_result: Optional[Callable[["ValidationResult"], None]] = None,
        verbose: bool = True,
    ) -> Dict[str, ValidationResult]:
        """
        Validate multiple URLs with rate limiting.

        Args:
            urls: List of URLs to validate.
            rate_limit_per_second: Maximum requests per second.
            max_runtime_seconds: Stop validating early when this many seconds
                have elapsed since *start_time*, leaving a 60-second safety
                buffer.  ``None`` means no limit.
            start_time: ``time.monotonic()`` value recorded at the start of
                the overall job.  When ``None`` the clock starts at the first
                call to this method.
            on_result: Optional callback invoked immediately after each URL is
                validated (before the inter-request delay).  Useful for
                incremental persistence so that partial results survive a
                timeout.
            verbose: When ``True`` (default) print a progress line and result
                for every URL.  Set to ``False`` to suppress per-URL output
                entirely; only the time-budget warning is still printed so
                that callers can tell when a run was cut short.

        Returns:
            Dictionary mapping URL to ValidationResult.  When stopped early
            the dict contains only the URLs that were actually validated.
        """
        results: Dict[str, ValidationResult] = {}
        delay = 1.0 / rate_limit_per_second if rate_limit_per_second > 0 else 0

        _start = start_time if start_time is not None else time.monotonic()
        # Stop validating this many seconds before the hard deadline so the
        # caller has time to flush results and upload artifacts.
        _safety_buffer = 60.0

        total = len(urls)
        for idx, url in enumerate(urls, 1):
            # Check remaining runtime budget before making the next request.
            if max_runtime_seconds is not None:
                elapsed = time.monotonic() - _start
                remaining = max_runtime_seconds - elapsed
                if remaining < _safety_buffer:
                    print(
                        f"  ⏱️  Time budget near limit "
                        f"({elapsed / 60:.1f}m elapsed, "
                        f"{remaining / 60:.1f}m remaining) "
                        f"— stopping after {idx - 1}/{total} URLs"
                    )
                    break

            if verbose:
                print(f"  [{idx}/{total}] Validating: {url}")
            result = await self.validate_url(url)
            results[url] = result

            if on_result is not None:
                on_result(result)

            if verbose:
                # Print result status
                if result.is_valid:
                    status_msg = f"✓ {result.status_code}" if result.status_code else "✓"
                    if result.redirected_to:
                        status_msg += f" → {result.redirected_to}"
                else:
                    status_msg = f"✗ {result.error_message or 'Failed'}"
                print(f"      {status_msg}")

            # Rate limiting delay
            if delay > 0:
                await asyncio.sleep(delay)

        return results
