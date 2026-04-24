"""Tests for batch coordinator service."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.services.batch_coordinator import BatchCoordinator, BatchConfig
from src.storage.schema import initialize_schema


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    
    # Initialize schema
    initialize_schema(f"sqlite:///{db_path}")
    
    yield db_path
    
    # Cleanup
    db_path.unlink(missing_ok=True)


@pytest.fixture
def coordinator(temp_db):
    """Create a batch coordinator with temp database."""
    return BatchCoordinator(temp_db)


def test_create_new_cycle(coordinator, temp_db, monkeypatch):
    """Test creating a new validation cycle."""
    # Mock the country list
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY", "SPAIN"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle()
    
    assert cycle_id is not None
    assert len(cycle_id) > 0
    
    # Check that countries were initialized
    conn = sqlite3.connect(temp_db)
    cursor = conn.execute(
        "SELECT country_code, status FROM validation_batch_state WHERE cycle_id = ?",
        (cycle_id,)
    )
    results = cursor.fetchall()
    conn.close()
    
    assert len(results) == 3
    assert all(status == "pending" for _, status in results)


def test_get_existing_cycle(coordinator, temp_db, monkeypatch):
    """Test getting an existing active cycle."""
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id_1 = coordinator.get_or_create_cycle()
    cycle_id_2 = coordinator.get_or_create_cycle()
    
    # Should return the same cycle ID
    assert cycle_id_1 == cycle_id_2


def test_get_next_batch(coordinator, temp_db, monkeypatch):
    """Test getting next batch of countries."""
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY", "SPAIN", "ITALY", "POLAND"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle()
    
    # Get first batch
    batch = coordinator.get_next_batch(cycle_id, batch_size=2)
    assert len(batch) == 2
    assert batch == ["FRANCE", "GERMANY"]
    
    # Get all pending countries (should still be 5)
    batch = coordinator.get_next_batch(cycle_id, batch_size=10)
    assert len(batch) == 5


def test_mark_batch_processing(coordinator, temp_db, monkeypatch):
    """Test marking countries as processing."""
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY", "SPAIN"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle()
    
    coordinator.mark_batch_processing(cycle_id, ["FRANCE", "GERMANY"])
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.execute(
        "SELECT country_code, status FROM validation_batch_state WHERE cycle_id = ? ORDER BY country_code",
        (cycle_id,)
    )
    results = {code: status for code, status in cursor.fetchall()}
    conn.close()
    
    assert results["FRANCE"] == "processing"
    assert results["GERMANY"] == "processing"
    assert results["SPAIN"] == "pending"


def test_mark_batch_completed(coordinator, temp_db, monkeypatch):
    """Test marking countries as completed."""
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle()
    
    coordinator.mark_batch_processing(cycle_id, ["FRANCE"])
    coordinator.mark_batch_completed(cycle_id, ["FRANCE"])
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.execute(
        "SELECT status FROM validation_batch_state WHERE cycle_id = ? AND country_code = ?",
        (cycle_id, "FRANCE")
    )
    status = cursor.fetchone()[0]
    conn.close()
    
    assert status == "completed"


def test_mark_batch_failed(coordinator, temp_db, monkeypatch):
    """Test marking a country as failed."""
    def mock_get_countries(self):
        return ["FRANCE"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle()
    
    coordinator.mark_batch_failed(cycle_id, "FRANCE", "Test error")
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.execute(
        "SELECT status, error_message FROM validation_batch_state WHERE cycle_id = ? AND country_code = ?",
        (cycle_id, "FRANCE")
    )
    status, error = cursor.fetchone()
    conn.close()
    
    assert status == "failed"
    assert error == "Test error"


def test_get_cycle_progress(coordinator, temp_db, monkeypatch):
    """Test getting cycle progress statistics."""
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY", "SPAIN", "ITALY"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle()
    
    # Mark some as completed and processing
    coordinator.mark_batch_completed(cycle_id, ["FRANCE"])
    coordinator.mark_batch_processing(cycle_id, ["GERMANY"])
    coordinator.mark_batch_failed(cycle_id, "SPAIN", "Test error")
    
    progress = coordinator.get_cycle_progress(cycle_id)
    
    assert progress["total"] == 4
    assert progress["completed"] == 1
    assert progress["processing"] == 1
    assert progress["pending"] == 1
    assert progress["failed"] == 1
    assert progress["is_complete"] is False


def test_cycle_completion(coordinator, temp_db, monkeypatch):
    """Test detecting when a cycle is complete."""
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle()
    
    # Complete all countries
    coordinator.mark_batch_completed(cycle_id, ["FRANCE", "GERMANY"])
    
    progress = coordinator.get_cycle_progress(cycle_id)
    
    assert progress["is_complete"] is True
    assert progress["pending"] == 0
    assert progress["processing"] == 0


def test_get_cycle_details(coordinator, temp_db, monkeypatch):
    """Test getting detailed cycle state."""
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY", "SPAIN"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle()
    
    coordinator.mark_batch_completed(cycle_id, ["FRANCE"])
    coordinator.mark_batch_processing(cycle_id, ["GERMANY"])
    
    details = coordinator.get_cycle_details(cycle_id)
    
    assert len(details) == 3
    assert details[0].country_code == "GERMANY"  # Processing first
    assert details[0].status == "processing"
    assert details[1].country_code == "SPAIN"  # Pending second
    assert details[1].status == "pending"
    assert details[2].country_code == "FRANCE"  # Completed last
    assert details[2].status == "completed"


def test_github_issue_tracking(coordinator, temp_db, monkeypatch):
    """Test GitHub issue number tracking."""
    def mock_get_countries(self):
        return ["FRANCE"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle(github_issue_number=123)
    
    progress = coordinator.get_cycle_progress(cycle_id)
    
    assert progress["issue_number"] == 123


def test_mark_batch_pending(coordinator, temp_db, monkeypatch):
    """Test marking a country back to pending (e.g., after timeout)."""
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY"]
    
    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)
    
    cycle_id = coordinator.get_or_create_cycle()
    
    # Mark as processing
    coordinator.mark_batch_processing(cycle_id, ["FRANCE", "GERMANY"])
    
    # Mark one back to pending (e.g., stopped early due to timeout)
    coordinator.mark_batch_pending(cycle_id, "GERMANY")
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.execute(
        "SELECT country_code, status FROM validation_batch_state WHERE cycle_id = ? ORDER BY country_code",
        (cycle_id,)
    )
    results = {code: status for code, status in cursor.fetchall()}
    conn.close()
    
    assert results["FRANCE"] == "processing"
    assert results["GERMANY"] == "pending"


def test_batch_config_defaults():
    """Test that BatchConfig has appropriate defaults for ~1 hour completion."""
    config = BatchConfig()
    
    # Batch size should be small enough to complete within ~1 hour
    assert config.batch_size == 4
    
    # Max runtime represents GitHub Actions workflow timeout limit
    # (CLI uses 50 min to leave 10 min buffer before this timeout)
    assert config.max_runtime_minutes == 60


def test_reset_failed_countries(coordinator, temp_db, monkeypatch):
    """Test resetting failed countries back to pending for retry."""
    def mock_get_countries(self):
        return ["FRANCE", "GERMANY", "SPAIN"]

    monkeypatch.setattr(BatchCoordinator, "_get_available_countries", mock_get_countries)

    cycle_id = coordinator.get_or_create_cycle()

    # Mark some countries as failed and one as completed
    coordinator.mark_batch_failed(cycle_id, "FRANCE", "Connection error")
    coordinator.mark_batch_failed(cycle_id, "GERMANY", "Timeout")
    coordinator.mark_batch_completed(cycle_id, ["SPAIN"])

    # Reset failed countries back to pending
    coordinator.reset_failed_countries(cycle_id)

    conn = sqlite3.connect(temp_db)
    cursor = conn.execute(
        "SELECT country_code, status, error_message FROM validation_batch_state WHERE cycle_id = ? ORDER BY country_code",
        (cycle_id,)
    )
    results = {code: (status, error) for code, status, error in cursor.fetchall()}
    conn.close()

    # Failed countries should now be pending with no error message
    assert results["FRANCE"][0] == "pending"
    assert results["FRANCE"][1] is None
    assert results["GERMANY"][0] == "pending"
    assert results["GERMANY"][1] is None
    # Completed country should remain completed
    assert results["SPAIN"][0] == "completed"

