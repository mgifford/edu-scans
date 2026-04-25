(function () {
  "use strict";

  var DEFAULT_PREVIEW_LIMIT = 5;
  var FULL_PREVIEW_THRESHOLD = 20;
  var panelSequence = 0;
  var dataPromises = {};
  var PLATFORM_KEYS = {
    Twitter: "twitter",
    X: "x",
    Bluesky: "bluesky",
    Mastodon: "mastodon",
    Facebook: "facebook",
    LinkedIn: "linkedin",
  };
  var COUNTRY_CODE_ALIASES = {
    Cyprus: "REPUBLIC_OF_CYPRUS",
    "United Kingdom": "UNITED_KINGDOM_UK",
  };
  var ACCESSIBILITY_LABELS = {
    Scanned: "scanned pages",
    Reachable: "reachable pages",
    "Has Statement": "pages with an accessibility statement",
    "In Footer": "pages with a footer accessibility statement link",
  };
  var VALIDATION_LABELS = {
    Total: "validated URLs",
    Valid: "URLs with at least one valid validation result",
    Invalid: "URLs with at least one invalid validation result",
  };
  var SOCIAL_METRIC_KEYS = {
    Scanned: "scanned",
    Reachable: "reachable",
    "No Social": "no_social",
    "Legacy-only": "legacy_only",
    Modern: "modern",
    Mixed: "mixed",
  };
  var TABLE_CONFIGS = [
    {
      id: "social",
      dataFile: "social-media-data.json",
      matchesTable: function (headers) {
        if (headers.indexOf("Country") === -1 || headers.indexOf("Scan Period") === -1) {
          return false;
        }
        return Object.keys(PLATFORM_KEYS).some(function (label) {
          return headers.indexOf(label) !== -1;
        });
      },
      getDataset: function (data) {
        return data || null;
      },
      getColumns: function (headers) {
        var columns = [];
        headers.forEach(function (label, index) {
          if (SOCIAL_METRIC_KEYS[label]) {
            columns.push({ index: index, label: label, key: SOCIAL_METRIC_KEYS[label], type: "metric" });
          }
          if (PLATFORM_KEYS[label]) {
            columns.push({ index: index, label: label, key: PLATFORM_KEYS[label], type: "platform" });
          }
        });
        return columns;
      },
      getRecords: function (dataset, country, column) {
        country = resolveCountryCode(country, dataset.platform_drilldowns || dataset.metric_drilldowns || {});
        if (column.type === "platform") {
          return (dataset.platform_drilldowns && dataset.platform_drilldowns[country] &&
            dataset.platform_drilldowns[country][column.key]) || [];
        }
        return (dataset.metric_drilldowns && dataset.metric_drilldowns[country] &&
          dataset.metric_drilldowns[country][column.key]) || [];
      },
      buildContext: function (country, column, count, records) {
        if (column.type === "metric") {
          return {
            availableCount: records.length,
            label: column.label,
            panelLabel: column.label + " pages for " + country,
            title: column.label + ": " + count.toLocaleString() + " pages in " + country,
            description: buildSocialMetricDescription(country, column.label, records.length),
            items: records.map(function (record) {
              return {
                href: record.page_url,
                label: record.page_url,
                meta: buildSocialMetricMeta(record),
              };
            }),
            csvHeaders: [
              "country",
              "metric",
              "page_url",
              "is_reachable",
              "social_tier",
              "twitter_links",
              "x_links",
              "facebook_links",
              "linkedin_links",
              "bluesky_links",
              "mastodon_links",
              "last_scanned",
            ],
            csvRows: records.map(function (record) {
              return [
                country,
                column.label,
                record.page_url,
                record.is_reachable ? "true" : "false",
                record.social_tier || "",
                joinPlatformLinks(record, "twitter"),
                joinPlatformLinks(record, "x"),
                joinPlatformLinks(record, "facebook"),
                joinPlatformLinks(record, "linkedin"),
                joinPlatformLinks(record, "bluesky"),
                joinPlatformLinks(record, "mastodon"),
                record.last_scanned || "",
              ];
            }),
            slug: country + "-" + column.label + "-social",
            titleAttribute: "Preview " + column.label + " pages for " + country,
          };
        }
        return {
          availableCount: records.length,
          label: column.label,
          panelLabel: column.label + " pages for " + country,
          title: column.label + ": " + count.toLocaleString() + " pages in " + country,
          description:
            records.length.toLocaleString() +
            " scanned pages in " +
            country +
            " had at least one " +
            column.label +
            " link.",
          items: records.map(function (record) {
            return {
              href: record.page_url,
              label: record.page_url,
              meta: record.detected_links && record.detected_links.length
                ? "Detected: " + record.detected_links[0]
                : "",
            };
          }),
          csvHeaders: ["country", "metric", "page_url", "detected_links"],
          csvRows: records.map(function (record) {
            return [
              country,
              column.label,
              record.page_url,
              (record.detected_links || []).join(" | "),
            ];
          }),
          slug: country + "-" + column.label,
          titleAttribute: "Preview " + column.label + " pages for " + country,
        };
      },
    },
    {
      id: "technology",
      dataFile: "technology-data.json",
      matchesTable: function (headers) {
        return (
          headers.indexOf("Country") !== -1 &&
          headers.indexOf("URLs Scanned") !== -1 &&
          headers.indexOf("Pages with Detections") !== -1 &&
          headers.indexOf("Available") !== -1 &&
          headers.indexOf("Last Scan") !== -1
        );
      },
      getDataset: function (data) {
        return data && data.country_drilldowns;
      },
      getColumns: function (headers) {
        return [
          { label: "URLs Scanned", key: "scanned" },
          { label: "Pages with Detections", key: "detected" },
        ]
          .map(function (column) {
            var index = headers.indexOf(column.label);
            return index === -1 ? null : { index: index, label: column.label, key: column.key };
          })
          .filter(Boolean);
      },
      getRecords: function (dataset, country, column) {
        country = resolveCountryCode(country, dataset);
        return (dataset[country] && dataset[country][column.key]) || [];
      },
      buildContext: function (country, column, count, records) {
        return {
          availableCount: records.length,
          label: column.label,
          panelLabel: column.label + " for " + country,
          title: column.label + ": " + count.toLocaleString() + " pages in " + country,
          description: buildTechnologyDescription(country, column.label, records.length),
          items: records.map(function (record) {
            return {
              href: record.page_url,
              label: record.page_url,
              meta: buildTechnologyMeta(record),
            };
          }),
          csvHeaders: [
            "country",
            "metric",
            "page_url",
            "technology_names",
            "error_message",
            "last_scanned",
          ],
          csvRows: records.map(function (record) {
            return [
              country,
              column.label,
              record.page_url,
              (record.technology_names || []).join(" | "),
              record.error_message || "",
              record.last_scanned || "",
            ];
          }),
          slug: country + "-" + column.label + "-technology",
          titleAttribute: "Preview " + column.label + " pages for " + country,
        };
      },
    },
    {
      id: "third-party-js",
      dataFile: "third-party-tools-data.json",
      matchesTable: function (headers) {
        return (
          headers.indexOf("Country") !== -1 &&
          headers.indexOf("Scanned") !== -1 &&
          headers.indexOf("Reachable") !== -1 &&
          headers.indexOf("URLs with 3rd-Party JS") !== -1 &&
          headers.indexOf("Known Service Loads") !== -1 &&
          headers.indexOf("Last Scan") !== -1
        );
      },
      getDataset: function (data) {
        return data && data.country_drilldowns;
      },
      getColumns: function (headers) {
        return [
          { label: "Scanned", key: "scanned" },
          { label: "Reachable", key: "reachable" },
          { label: "URLs with 3rd-Party JS", key: "urls_with_scripts" },
          { label: "Known Service Loads", key: "service_loads" },
        ]
          .map(function (column) {
            var index = headers.indexOf(column.label);
            return index === -1 ? null : { index: index, label: column.label, key: column.key };
          })
          .filter(Boolean);
      },
      getRecords: function (dataset, country, column) {
        country = resolveCountryCode(country, dataset);
        return (dataset[country] && dataset[country][column.key]) || [];
      },
      buildContext: function (country, column, count, records) {
        var isServiceLoad = column.key === "service_loads";
        return {
          availableCount: records.length,
          label: column.label,
          panelLabel: column.label + " for " + country,
          title: column.label + ": " + count.toLocaleString() + " records in " + country,
          description: buildThirdPartyDescription(country, column.label, records.length),
          items: records.map(function (record) {
            return {
              href: record.page_url,
              label: isServiceLoad ? record.service_name + " on " + record.page_url : record.page_url,
              meta: buildThirdPartyMeta(record, column.key),
            };
          }),
          csvHeaders: isServiceLoad
            ? ["country", "metric", "page_url", "service_name", "src", "host", "version", "categories", "last_scanned"]
            : ["country", "metric", "page_url", "service_names", "script_sources", "last_scanned"],
          csvRows: records.map(function (record) {
            if (isServiceLoad) {
              return [
                country,
                column.label,
                record.page_url,
                record.service_name || "",
                record.src || "",
                record.host || "",
                record.version || "",
                (record.categories || []).join(" | "),
                record.last_scanned || "",
              ];
            }
            return [
              country,
              column.label,
              record.page_url,
              (record.service_names || []).join(" | "),
              (record.scripts || []).map(function (script) { return script.src || ""; }).join(" | "),
              record.last_scanned || "",
            ];
          }),
          slug: country + "-" + column.label + "-third-party",
          titleAttribute: "Preview " + column.label + " records for " + country,
        };
      },
    },
    {
      id: "scan-progress-validation",
      dataFile: "scan-progress-data.json",
      matchesTable: function (headers) {
        return (
          headers.indexOf("Country") !== -1 &&
          headers.indexOf("Total") !== -1 &&
          headers.indexOf("Valid") !== -1 &&
          headers.indexOf("Invalid") !== -1 &&
          headers.indexOf("Scan Period") !== -1 &&
          headers.indexOf("Coverage") !== -1
        );
      },
      getDataset: function (data) {
        return data && data.url_validation_drilldowns;
      },
      getColumns: function (headers) {
        return ["Total", "Valid", "Invalid"]
          .map(function (label) {
            var index = headers.indexOf(label);
            return index === -1 ? null : { index: index, label: label, key: label.toLowerCase() };
          })
          .filter(Boolean);
      },
      getRecords: function (dataset, country, column) {
        country = resolveCountryCode(country, dataset);
        return (dataset[country] && dataset[country][column.key]) || [];
      },
      buildContext: function (country, column, count, records) {
        return {
          availableCount: records.length,
          label: column.label,
          panelLabel: VALIDATION_LABELS[column.label] + " for " + country,
          title:
            column.label + ": " + count.toLocaleString() + " " + VALIDATION_LABELS[column.label] + " in " + country,
          description: buildValidationDescription(country, column.label, records.length),
          items: records.map(function (record) {
            return {
              href: record.url,
              label: record.url,
              meta: buildValidationMeta(record, column.label),
            };
          }),
          csvHeaders: [
            "country",
            "metric",
            "url",
            "latest_status",
            "latest_status_code",
            "latest_error_message",
            "latest_redirected_to",
            "latest_redirect_chain",
            "latest_failure_count",
            "latest_validated_at",
            "ever_valid",
            "ever_invalid",
            "latest_valid_at",
            "latest_invalid_at",
          ],
          csvRows: records.map(function (record) {
            return [
              country,
              column.label,
              record.url,
              record.latest_status || "",
              record.latest_status_code == null ? "" : String(record.latest_status_code),
              record.latest_error_message || "",
              record.latest_redirected_to || "",
              record.latest_redirect_chain || "",
              record.latest_failure_count == null ? "" : String(record.latest_failure_count),
              record.latest_validated_at || "",
              record.ever_valid ? "true" : "false",
              record.ever_invalid ? "true" : "false",
              record.latest_valid_at || "",
              record.latest_invalid_at || "",
            ];
          }),
          slug: country + "-" + column.label + "-validation",
          titleAttribute: "Preview " + column.label + " validation URLs for " + country,
        };
      },
    },
    {
      id: "accessibility",
      dataFile: "accessibility-data.json",
      matchesTable: function (headers) {
        if (headers.indexOf("Country") === -1 || headers.indexOf("Scan Period") === -1) {
          return false;
        }
        return (
          headers.indexOf("Has Statement") !== -1 &&
          headers.indexOf("In Footer") !== -1 &&
          headers.indexOf("Reachable") !== -1
        );
      },
      getDataset: function (data) {
        return data && data.country_detail;
      },
      getColumns: function (headers) {
        var columns = [];
        Object.keys(ACCESSIBILITY_LABELS).forEach(function (label) {
          var index = headers.indexOf(label);
          if (index !== -1) {
            columns.push({ index: index, label: label });
          }
        });
        return columns;
      },
      getRecords: function (dataset, country, column) {
        country = resolveCountryCode(country, dataset);
        var countryDetail = dataset[country];
        if (!countryDetail) {
          return [];
        }

        if (column.label === "Scanned") {
          return [].concat(
            countryDetail.pages_with_statement || [],
            countryDetail.pages_without_statement || [],
            countryDetail.unreachable_pages || []
          );
        }
        if (column.label === "Reachable") {
          return [].concat(
            countryDetail.pages_with_statement || [],
            countryDetail.pages_without_statement || []
          );
        }
        if (column.label === "Has Statement") {
          return countryDetail.pages_with_statement || [];
        }
        if (column.label === "In Footer") {
          return (countryDetail.pages_with_statement || []).filter(function (record) {
            return record.found_in_footer;
          });
        }
        return [];
      },
      buildContext: function (country, column, count, records) {
        return {
          availableCount: records.length,
          label: column.label,
          panelLabel: ACCESSIBILITY_LABELS[column.label] + " for " + country,
          title:
            column.label + ": " + count.toLocaleString() + " " + ACCESSIBILITY_LABELS[column.label] + " in " + country,
          description: buildAccessibilityDescription(country, column.label, records.length),
          items: records.map(function (record) {
            return {
              href: record.url,
              label: record.url,
              meta: buildAccessibilityMeta(record),
            };
          }),
          csvHeaders: [
            "country",
            "metric",
            "page_url",
            "domain",
            "is_reachable",
            "has_statement",
            "found_in_footer",
            "statement_links",
            "matched_terms",
            "error_message",
            "last_scanned",
          ],
          csvRows: records.map(function (record) {
            return [
              country,
              column.label,
              record.url,
              record.domain || "",
              record.is_reachable ? "true" : "false",
              record.has_statement ? "true" : "false",
              record.found_in_footer ? "true" : "false",
              (record.statement_links || []).join(" | "),
              (record.matched_terms || []).join(" | "),
              record.error_message || "",
              record.last_scanned || "",
            ];
          }),
          slug: country + "-" + column.label + "-accessibility",
          titleAttribute: "Preview " + column.label + " evidence for " + country,
        };
      },
    },
  ];

  function init() {
    var tableEntries = findDrilldownTables();
    enhanceScrollableTables();
    window.addEventListener("resize", enhanceScrollableTables);

    initLighthouseInstitutionTable();

    if (!tableEntries.length) {
      return;
    }

    tableEntries.forEach(function (entry) {
      makeSortable(entry.table);
    });

    TABLE_CONFIGS.forEach(function (config) {
      var matchingEntries = tableEntries.filter(function (entry) {
        return entry.config.id === config.id;
      });
      if (!matchingEntries.length) {
        return;
      }

      loadDrilldownData(config.dataFile).then(function (data) {
        var dataset = config.getDataset(data);
        if (!dataset) {
          return;
        }
        matchingEntries.forEach(function (entry) {
          enhanceTable(entry.table, config, dataset);
        });
      });
    });

    document.addEventListener("click", handleDocumentClick);
    document.addEventListener("keydown", handleDocumentKeydown);
  }

  function initLighthouseInstitutionTable() {
    var table = document.getElementById("lighthouse-institution-table");
    if (!table) {
      return;
    }

    makeSortable(table);

    // Default sort: A11y descending (column index 4 — most accessible first)
    var headers = Array.from(table.querySelectorAll("thead th"));
    if (headers.length > 4) {
      headers.forEach(function (h) {
        h.setAttribute("aria-sort", "none");
      });
      headers[4].setAttribute("aria-sort", "descending");
      sortTable(table, 4, false);
    }

    var input = document.getElementById("lh-institution-search");
    var countEl = document.getElementById("lh-institution-count");
    if (!input) {
      return;
    }

    function filterTable() {
      var query = input.value.toLowerCase().trim();
      var rows = Array.from(table.querySelectorAll("tbody tr"));
      var visible = 0;
      rows.forEach(function (row) {
        var searchText = row.dataset.search || row.textContent.toLowerCase();
        var match = !query || searchText.indexOf(query) !== -1;
        row.hidden = !match;
        if (match) {
          visible++;
        }
      });
      if (countEl) {
        countEl.textContent =
          "Showing " +
          visible.toLocaleString() +
          " of " +
          rows.length.toLocaleString() +
          " institutions";
      }
    }

    input.addEventListener("input", filterTable);
    input.addEventListener("search", filterTable);
  }

  function enhanceScrollableTables() {
    document.querySelectorAll("table").forEach(function (table) {
      var isScrollable = table.scrollWidth > table.clientWidth + 1;
      if (isScrollable) {
        table.setAttribute("tabindex", "0");
        if (!table.hasAttribute("aria-label")) {
          var heading = findTableHeading(table);
          if (heading) {
            table.setAttribute("aria-label", heading + " table");
          }
        }
      } else {
        table.removeAttribute("tabindex");
        if (table.getAttribute("aria-label") && / table$/.test(table.getAttribute("aria-label"))) {
          table.removeAttribute("aria-label");
        }
      }
    });
  }

  function findTableHeading(table) {
    var element = table.previousElementSibling;
    while (element) {
      if (/^H[1-6]$/.test(element.tagName)) {
        return element.textContent.trim();
      }
      element = element.previousElementSibling;
    }
    return "";
  }

  function loadDrilldownData(dataFile) {
    if (!dataPromises[dataFile]) {
      dataPromises[dataFile] = fetch(new URL(dataFile, window.location.href).href, {
        headers: { Accept: "application/json" },
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("Unable to load drilldown data");
          }
          return response.json();
        })
        .catch(function () {
          return null;
        });
    }
    return dataPromises[dataFile];
  }

  function findDrilldownTables() {
    return Array.from(document.querySelectorAll("table"))
      .map(function (table) {
        var headers = getHeaderLabels(table);
        var config = TABLE_CONFIGS.find(function (candidate) {
          return candidate.matchesTable(headers);
        });
        if (!config) {
          return null;
        }
        return { table: table, config: config };
      })
      .filter(Boolean);
  }

  function getHeaderLabels(table) {
    return Array.from(table.querySelectorAll("thead th")).map(function (cell) {
      return cell.textContent.trim();
    });
  }

  function makeSortable(table) {
    if (table.dataset.sortableReady === "true") {
      return;
    }
    table.dataset.sortableReady = "true";
    table.classList.add("sm-sortable");

    var headers = Array.from(table.querySelectorAll("thead th"));
    headers.forEach(function (header, columnIndex) {
      header.setAttribute("aria-sort", "none");
      header.setAttribute("tabindex", "0");

      function sortHandler(event) {
        if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") {
          return;
        }
        if (event.type === "keydown") {
          event.preventDefault();
        }

        var ascending = header.getAttribute("aria-sort") !== "ascending";
        headers.forEach(function (cell) {
          cell.setAttribute("aria-sort", "none");
        });
        header.setAttribute("aria-sort", ascending ? "ascending" : "descending");
        sortTable(table, columnIndex, ascending);
      }

      header.addEventListener("click", sortHandler);
      header.addEventListener("keydown", sortHandler);
    });
  }

  function sortTable(table, columnIndex, ascending) {
    var tbody = table.querySelector("tbody");
    if (!tbody) {
      return;
    }

    var rows = Array.from(tbody.querySelectorAll("tr"));
    var totalRow = null;
    if (rows.length) {
      var lastRow = rows[rows.length - 1];
      var firstCell = lastRow.querySelector("td");
      if (firstCell && firstCell.textContent.indexOf("Total") !== -1) {
        totalRow = rows.pop();
      }
    }

    rows.sort(function (left, right) {
      var leftValue = getSortableCellValue(left, columnIndex);
      var rightValue = getSortableCellValue(right, columnIndex);

      if (leftValue === null) {
        return ascending ? 1 : -1;
      }
      if (rightValue === null) {
        return ascending ? -1 : 1;
      }
      if (typeof leftValue === "number" && typeof rightValue === "number") {
        return ascending ? leftValue - rightValue : rightValue - leftValue;
      }
      return ascending
        ? String(leftValue).localeCompare(String(rightValue))
        : String(rightValue).localeCompare(String(leftValue));
    });

    rows.forEach(function (row) {
      tbody.appendChild(row);
    });
    if (totalRow) {
      tbody.appendChild(totalRow);
    }
  }

  function getSortableCellValue(row, columnIndex) {
    var cell = row.querySelectorAll("td")[columnIndex];
    if (!cell) {
      return null;
    }
    if (cell.dataset.sortVal !== undefined) {
      return parseFloat(cell.dataset.sortVal);
    }

    var text = cell.textContent.trim();
    if (!text || text === "—") {
      return null;
    }
    if (text.slice(-1) === "%") {
      return parseFloat(text);
    }

    var numberValue = parseInt(text.replace(/,/g, ""), 10);
    return isNaN(numberValue) ? text.toLowerCase() : numberValue;
  }

  function enhanceTable(table, config, dataset) {
    if (table.dataset.drilldownReadyConfig === config.id) {
      return;
    }
    table.dataset.drilldownReadyConfig = config.id;

    var headers = getHeaderLabels(table);
    var countryColumn = headers.indexOf("Country");
    var columns = config.getColumns(headers);

    table.querySelectorAll("tbody tr").forEach(function (row) {
      var cells = row.querySelectorAll("td");
      if (!cells.length || !cells[countryColumn]) {
        return;
      }

      var country = cells[countryColumn].textContent.trim();
      if (country.indexOf("Total") !== -1) {
        return;
      }

      columns.forEach(function (column) {
        var cell = cells[column.index];
        if (!cell) {
          return;
        }

        var rawValue = cell.textContent.replace(/,/g, "").trim();
        var count = parseInt(rawValue, 10);
        if (isNaN(count) || count <= 0) {
          return;
        }

        var records = config.getRecords(dataset, country, column);
        if (!records.length) {
          return;
        }

        var context = config.buildContext(country, column, count, records);
        cell.dataset.sortVal = String(count);
        cell.textContent = "";
        cell.appendChild(buildDrilldownControl(context, count));
      });
    });
  }

  function buildDrilldownControl(context, count) {
    var wrapper = document.createElement("span");
    wrapper.className = "table-drilldown";

    var trigger = document.createElement("button");
    trigger.className = "table-drilldown__trigger";
    trigger.type = "button";
    trigger.textContent = count.toLocaleString();
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-haspopup", "dialog");
    trigger.setAttribute("title", context.titleAttribute);

    var panel = document.createElement("div");
    panel.className = "table-drilldown__panel";
    panel.hidden = true;
    panel.id = "table-drilldown-panel-" + (++panelSequence);
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", context.panelLabel);
    trigger.setAttribute("aria-controls", panel.id);

    panel.appendChild(buildPanelTitle(context.title));
    panel.appendChild(buildPanelDescription(context.description, count, context.availableCount));
    panel.appendChild(buildPreviewList(context.items, context.availableCount));
    panel.appendChild(buildPreviewSummary(count, context.availableCount));
    panel.appendChild(buildPanelHint());
    panel.appendChild(buildDownloadButton(context));

    wrapper.appendChild(trigger);
    wrapper.appendChild(panel);

    wrapper.addEventListener("mouseenter", function () {
      openPanel(wrapper, false);
    });
    wrapper.addEventListener("mouseleave", function (event) {
      closePanelIfIdle(wrapper, event);
    });
    wrapper.addEventListener("focusin", function () {
      openPanel(wrapper, false);
    });
    wrapper.addEventListener("focusout", function (event) {
      closePanelIfIdle(wrapper, event);
    });
    trigger.addEventListener("click", function (event) {
      event.preventDefault();
      togglePinned(wrapper);
    });

    return wrapper;
  }

  function buildPanelTitle(titleText) {
    var title = document.createElement("p");
    title.className = "table-drilldown__title";
    title.textContent = titleText;
    return title;
  }

  function buildPanelDescription(descriptionText, count, availableCount) {
    var text = document.createElement("p");
    text.className = "table-drilldown__description";
    text.textContent = descriptionText;
    if (count !== availableCount) {
      text.textContent += " Preview and CSV use the currently available drilldown records.";
    }
    return text;
  }

  function buildPreviewList(items, availableCount) {
    var previewLimit = getPreviewLimit(availableCount);
    var list = document.createElement("ul");
    list.className = "table-drilldown__list";

    items.slice(0, previewLimit).forEach(function (itemData) {
      var item = document.createElement("li");
      if (itemData.href) {
        var link = document.createElement("a");
        link.href = itemData.href;
        link.textContent = itemData.label;
        link.rel = "noopener noreferrer";
        item.appendChild(link);
      } else {
        item.textContent = itemData.label;
      }

      if (itemData.meta) {
        var meta = document.createElement("span");
        meta.className = "table-drilldown__meta";
        meta.textContent = itemData.meta;
        item.appendChild(meta);
      }

      list.appendChild(item);
    });

    return list;
  }

  function buildPreviewSummary(count, availableCount) {
    var previewLimit = getPreviewLimit(availableCount);
    var summary = document.createElement("p");
    summary.className = "table-drilldown__summary";
    if (availableCount > previewLimit) {
      summary.textContent =
        "Showing the first " +
        previewLimit +
        " of " +
        availableCount.toLocaleString() +
        " matching pages.";
    } else {
      summary.textContent =
        "Showing all " +
        availableCount.toLocaleString() +
        " matching pages in the preview.";
    }
    if (count > availableCount) {
      summary.textContent += " The table count is higher than the current downloadable subset.";
    }
    return summary;
  }

  function getPreviewLimit(availableCount) {
    if (availableCount <= FULL_PREVIEW_THRESHOLD) {
      return availableCount;
    }
    return DEFAULT_PREVIEW_LIMIT;
  }

  function buildPanelHint() {
    var hint = document.createElement("p");
    hint.className = "table-drilldown__hint";
    hint.textContent =
      "Hover or focus previews this panel. Activate the number to keep it open and download the full CSV.";
    return hint;
  }

  function resolveCountryCode(country, dataset) {
    if (!country) {
      return country;
    }
    if (dataset && dataset[country]) {
      return country;
    }
    if (COUNTRY_CODE_ALIASES[country]) {
      return COUNTRY_CODE_ALIASES[country];
    }
    return country.toUpperCase().replace(/\s+/g, "_");
  }

  function buildSocialMetricDescription(country, label, availableCount) {
    if (label === "Scanned") {
      return availableCount.toLocaleString() + " scanned pages in " + country + " are listed here.";
    }
    if (label === "Reachable") {
      return availableCount.toLocaleString() + " reachable pages in " + country + " are listed here.";
    }
    if (label === "No Social") {
      return availableCount.toLocaleString() + " reachable pages in " + country + " had no detected social-media links.";
    }
    if (label === "Legacy-only") {
      return availableCount.toLocaleString() + " pages in " + country + " used only legacy social platforms.";
    }
    if (label === "Modern") {
      return availableCount.toLocaleString() + " pages in " + country + " used only modern/open social platforms.";
    }
    if (label === "Mixed") {
      return availableCount.toLocaleString() + " pages in " + country + " mixed legacy and modern social links.";
    }
    return availableCount.toLocaleString() + " social-media records are available for " + country + ".";
  }

  function buildSocialMetricMeta(record) {
    var parts = [];
    if (record.social_tier) {
      parts.push("Tier: " + record.social_tier);
    }
    Object.keys(PLATFORM_KEYS).forEach(function (label) {
      var platformKey = PLATFORM_KEYS[label];
      var links = record.links_by_platform && record.links_by_platform[platformKey];
      if (links && links.length) {
        parts.push(label + ": " + links[0]);
      }
    });
    if (record.last_scanned) {
      parts.push("Latest scan: " + record.last_scanned);
    }
    return parts.join(" | ");
  }

  function joinPlatformLinks(record, platformKey) {
    return record.links_by_platform && record.links_by_platform[platformKey]
      ? record.links_by_platform[platformKey].join(" | ")
      : "";
  }

  function buildTechnologyDescription(country, label, availableCount) {
    if (label === "URLs Scanned") {
      return availableCount.toLocaleString() + " scanned pages in " + country + " are listed here.";
    }
    if (label === "Pages with Detections") {
      return availableCount.toLocaleString() + " pages counted in the technology detections column for " + country + " are listed here.";
    }
    return availableCount.toLocaleString() + " technology records are available for " + country + ".";
  }

  function buildTechnologyMeta(record) {
    var parts = [];
    if (record.technology_names && record.technology_names.length) {
      parts.push("Technologies: " + record.technology_names.slice(0, 3).join(", "));
    } else if (record.error_message) {
      parts.push("Error: " + record.error_message);
    } else {
      parts.push("No technologies identified in saved result");
    }
    if (record.last_scanned) {
      parts.push("Latest scan: " + record.last_scanned);
    }
    return parts.join(" | ");
  }

  function buildThirdPartyDescription(country, label, availableCount) {
    if (label === "Scanned") {
      return availableCount.toLocaleString() + " scanned pages in " + country + " are listed here.";
    }
    if (label === "Reachable") {
      return availableCount.toLocaleString() + " reachable pages in " + country + " are listed here.";
    }
    if (label === "URLs with 3rd-Party JS") {
      return availableCount.toLocaleString() + " pages in " + country + " loaded at least one third-party script.";
    }
    if (label === "Known Service Loads") {
      return availableCount.toLocaleString() + " known third-party service loads in " + country + " are listed here.";
    }
    return availableCount.toLocaleString() + " third-party records are available for " + country + ".";
  }

  function buildThirdPartyMeta(record, key) {
    var parts = [];
    if (key === "service_loads") {
      if (record.src) {
        parts.push("Source: " + record.src);
      }
      if (record.categories && record.categories.length) {
        parts.push("Categories: " + record.categories.join(", "));
      }
    } else if (record.service_names && record.service_names.length) {
      parts.push("Services: " + record.service_names.slice(0, 3).join(", "));
    } else {
      parts.push("No known third-party services identified");
    }
    if (record.last_scanned) {
      parts.push("Latest scan: " + record.last_scanned);
    }
    return parts.join(" | ");
  }

  function buildDownloadButton(context) {
    var button = document.createElement("button");
    button.className = "table-drilldown__download";
    button.type = "button";
    button.textContent = "Download CSV";
    button.addEventListener("click", function () {
      downloadCsv(context);
    });
    return button;
  }

  function buildAccessibilityDescription(country, label, availableCount) {
    if (label === "Scanned") {
      return availableCount.toLocaleString() + " scanned pages in " + country + " have detailed accessibility evidence.";
    }
    if (label === "Reachable") {
      return availableCount.toLocaleString() + " reachable pages in " + country + " are listed here.";
    }
    if (label === "Has Statement") {
      return availableCount.toLocaleString() + " pages in " + country + " include at least one accessibility statement link.";
    }
    if (label === "In Footer") {
      return availableCount.toLocaleString() + " pages in " + country + " expose the statement link from the footer.";
    }
    return availableCount.toLocaleString() + " accessibility records are available for " + country + ".";
  }

  function buildAccessibilityMeta(record) {
    var parts = [];
    if (record.domain) {
      parts.push("Domain: " + record.domain);
    }
    if (record.found_in_footer) {
      parts.push("Found in footer");
    }
    if (record.statement_links && record.statement_links.length) {
      parts.push("Statement: " + record.statement_links[0]);
    }
    if (record.error_message) {
      parts.push("Error: " + record.error_message);
    } else if (record.matched_terms && record.matched_terms.length) {
      parts.push("Matched: " + record.matched_terms.slice(0, 2).join(", "));
    }
    return parts.join(" | ");
  }

  function buildValidationDescription(country, label, availableCount) {
    if (label === "Total") {
      return availableCount.toLocaleString() + " validated URLs in " + country + " are available here.";
    }
    if (label === "Valid") {
      return availableCount.toLocaleString() + " URLs in " + country + " returned a valid result at least once during the scan period.";
    }
    if (label === "Invalid") {
      return availableCount.toLocaleString() + " URLs in " + country + " returned an invalid result at least once during the scan period.";
    }
    return availableCount.toLocaleString() + " validation URLs are available for " + country + ".";
  }

  function buildValidationMeta(record, label) {
    var parts = [];
    if (label !== "Total") {
      parts.push(label === "Invalid" ? "Includes invalid result in scan period" : "Includes valid result in scan period");
    }
    if (record.latest_status) {
      parts.push("Latest status: " + record.latest_status);
    }
    if (record.latest_status_code != null && record.latest_status_code !== "") {
      parts.push("HTTP " + record.latest_status_code);
    }
    if (record.latest_redirected_to) {
      parts.push("Redirected to: " + record.latest_redirected_to);
    }
    if (record.latest_error_message) {
      parts.push("Error: " + record.latest_error_message);
    }
    if (record.latest_validated_at) {
      parts.push("Latest check: " + record.latest_validated_at);
    }
    return parts.join(" | ");
  }

  function togglePinned(wrapper) {
    var pinned = wrapper.dataset.pinned === "true";
    if (pinned) {
      wrapper.dataset.pinned = "false";
      closePanel(wrapper);
      return;
    }
    closeAllPanels(wrapper);
    wrapper.dataset.pinned = "true";
    openPanel(wrapper, true);
  }

  function openPanel(wrapper, preservePinned) {
    var trigger = wrapper.querySelector(".table-drilldown__trigger");
    var panel = wrapper.querySelector(".table-drilldown__panel");
    if (!trigger || !panel) {
      return;
    }
    if (!preservePinned && wrapper.dataset.pinned !== "true") {
      wrapper.dataset.pinned = "false";
    }
    wrapper.classList.add("is-open");
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
  }

  function closePanel(wrapper) {
    var trigger = wrapper.querySelector(".table-drilldown__trigger");
    var panel = wrapper.querySelector(".table-drilldown__panel");
    if (!trigger || !panel) {
      return;
    }
    wrapper.classList.remove("is-open");
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }

  function closePanelIfIdle(wrapper, event) {
    var relatedTarget = event.relatedTarget;
    if (relatedTarget && wrapper.contains(relatedTarget)) {
      return;
    }
    if (wrapper.dataset.pinned === "true") {
      return;
    }
    closePanel(wrapper);
  }

  function closeAllPanels(exceptWrapper) {
    document.querySelectorAll(".table-drilldown").forEach(function (wrapper) {
      if (wrapper === exceptWrapper) {
        return;
      }
      wrapper.dataset.pinned = "false";
      closePanel(wrapper);
    });
  }

  function handleDocumentClick(event) {
    var target = event.target;
    if (target.closest(".table-drilldown")) {
      return;
    }
    closeAllPanels(null);
  }

  function handleDocumentKeydown(event) {
    if (event.key !== "Escape") {
      return;
    }
    closeAllPanels(null);
  }

  function downloadCsv(context) {
    var lines = [context.csvHeaders.join(",")];
    context.csvRows.forEach(function (row) {
      lines.push(
        row.map(function (value) {
          return csvEscape(value);
        }).join(",")
      );
    });

    var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    var slug = context.slug
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    link.href = url;
    link.download = slug + "-pages.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function csvEscape(value) {
    return '"' + String(value || "").replace(/"/g, '""') + '"';
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
