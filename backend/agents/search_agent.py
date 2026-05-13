"""
agents/search_agent.py
----------------------
Real job search using JSearch API via RapidAPI.
Searches worldwide — any country, any job type, remote or on-site.
"""

import os
import time
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv, load_dotenv as _load_dotenv
from backend.core import observability

ROOT             = Path(__file__).parent.parent.parent

load_dotenv()

# Load .env from project root using absolute path
_load_dotenv(dotenv_path=ROOT / ".env", override=True)

JSEARCH_API_KEY  = os.getenv("JSEARCH_API_KEY", "")
JSEARCH_HOST     = "jsearch.p.rapidapi.com"
JSEARCH_BASE_URL = "https://jsearch.p.rapidapi.com"
JSEARCH_TIMEOUT  = int(os.getenv("PERSONAL_OS_TOOL_TIMEOUT_SECONDS", "15"))
TOOL_RETRIES     = int(os.getenv("PERSONAL_OS_TOOL_RETRIES", "2"))
logger = observability.get_logger(__name__)


# ─────────────────────────────────────────────
#  Headers
# ─────────────────────────────────────────────

def _headers():
    return {
        "x-rapidapi-key":  JSEARCH_API_KEY,
        "x-rapidapi-host": JSEARCH_HOST,
        "Content-Type":    "application/json"
    }


# ─────────────────────────────────────────────
#  Core job search
# ─────────────────────────────────────────────

def search_jobs(
    query:       str,
    location:    str  = "",
    remote_only: bool = False,
    num_pages:   int  = 1,
    date_posted: str  = "all",
    save_to_db:  bool = True
) -> dict:
    """
    Search for jobs worldwide using JSearch API.

    Args:
        query:       Job title or keywords e.g. "SQA Engineer"
        location:    Country or city e.g. "Japan", "Tokyo", "Germany"
                     Leave empty for worldwide search
        remote_only: True to search remote jobs only
        num_pages:   Number of result pages (1 page = 10 jobs)
        date_posted: "all", "today", "3days", "week", "month"
        save_to_db:  Whether to save results to jobs module

    Returns:
        {
            "success": True/False,
            "message": "Found X jobs...",
            "jobs":    [...],
            "total":   number
        }
    """
    if not JSEARCH_API_KEY:
        return {
            "success": False,
            "message": "JSearch API key not set. Add JSEARCH_API_KEY to your .env file.",
            "jobs":    []
        }

    # Build search query
    search_query = query
    if location:
        search_query = query + " in " + location
    if remote_only:
        search_query = query + " remote"

    params = {
        "query":       search_query,
        "num_pages":   str(num_pages),
        "date_posted": date_posted,
    }

    try:
        response = _get_with_retries(
            JSEARCH_BASE_URL + "/search",
            headers=_headers(),
            params=params,
            timeout=JSEARCH_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()

    except requests.exceptions.Timeout:
        return {"success": False, "message": "Search timed out. Try again.", "jobs": []}
    except requests.exceptions.HTTPError as e:
        return {"success": False, "message": "API error: " + str(e), "jobs": []}
    except Exception as e:
        return {"success": False, "message": "Search failed: " + str(e), "jobs": []}

    # Parse results
    raw_jobs = data.get("data", [])
    jobs     = [_parse_job(j) for j in raw_jobs]

    # Save to database
    saved = 0
    if save_to_db and jobs:
        saved = _save_jobs(jobs)

    total   = len(jobs)
    message = (
        "Found " + str(total) + " jobs for '" + query + "'" +
        (" in " + location if location else " worldwide") +
        (" (remote only)" if remote_only else "") + "."
    )
    if saved > 0:
        message += " Saved " + str(saved) + " to your jobs module."

    return {
        "success": True,
        "message": message,
        "jobs":    jobs,
        "total":   total,
        "query":   query,
        "location": location
    }


# ─────────────────────────────────────────────
#  Job details
# ─────────────────────────────────────────────

def get_job_details(job_id: str) -> dict:
    """
    Get full details for a specific job by its ID.
    Use the job_id returned from search_jobs.
    """
    if not JSEARCH_API_KEY:
        return {"success": False, "message": "API key not set.", "job": None}

    try:
        response = _get_with_retries(
            JSEARCH_BASE_URL + "/job-details",
            headers=_headers(),
            params={"job_id": job_id},
            timeout=JSEARCH_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        jobs = data.get("data", [])
        if not jobs:
            return {"success": False, "message": "Job not found.", "job": None}

        return {
            "success": True,
            "job":     _parse_job(jobs[0]),
            "message": "Job details retrieved."
        }
    except Exception as e:
        return {"success": False, "message": "Failed: " + str(e), "job": None}


# ─────────────────────────────────────────────
#  Salary estimate
# ─────────────────────────────────────────────

def get_salary_estimate(job_title: str, location: str = "") -> dict:
    """
    Get salary estimate for a job title and location.
    """
    if not JSEARCH_API_KEY:
        return {"success": False, "message": "API key not set."}

    try:
        params = {
            "job_title":      job_title,
            "location":       location or "worldwide",
            "radius":         "100"
        }
        response = _get_with_retries(
            JSEARCH_BASE_URL + "/estimated-salary",
            headers=_headers(),
            params=params,
            timeout=JSEARCH_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        jobs = data.get("data", [])

        if not jobs:
            return {
                "success": False,
                "message": "No salary data found for " + job_title + " in " + location
            }

        salaries = jobs[0]
        message  = (
            "Salary estimate for " + job_title +
            (" in " + location if location else "") + ": " +
            _format_salary(salaries.get("min_salary"), salaries.get("max_salary"),
                           salaries.get("median_salary"), salaries.get("salary_currency","USD"))
        )

        return {
            "success":  True,
            "message":  message,
            "min":      salaries.get("min_salary"),
            "max":      salaries.get("max_salary"),
            "median":   salaries.get("median_salary"),
            "currency": salaries.get("salary_currency", "USD"),
            "period":   salaries.get("salary_period", "YEAR")
        }

    except Exception as e:
        return {"success": False, "message": "Salary lookup failed: " + str(e)}


def scrape_company_jobs(company: str, query: str = "") -> dict:
    """Compatibility wrapper for scrape actions using the job-search backend."""
    search_query = query or (company + " jobs")
    return search_jobs(search_query, company, save_to_db=False)


def search_web(query: str) -> dict:
    """Scrape readable text from a URL for generic scrape actions."""
    if not query.startswith(("http://", "https://")):
        return {
            "success": False,
            "message": "Generic scraping expects an http(s) URL.",
            "results": [],
            "query": query,
        }
    try:
        from backend.core import rag

        result = rag.ingest_url(query)
        return {
            "success": True,
            "message": "Scraped and indexed " + query + ".",
            "results": [result],
            "query": query,
        }
    except Exception as e:
        return {"success": False, "message": "Scrape failed: " + str(e), "results": [], "query": query}


def _get_with_retries(url: str, **kwargs):
    last_error = None
    for attempt in range(TOOL_RETRIES + 1):
        try:
            observability.log_event(logger, "tool.http", tool="jsearch", url=url, attempt=attempt + 1)
            return requests.get(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt >= TOOL_RETRIES:
                break
            delay = 0.25 * (2 ** attempt)
            observability.log_event(logger, "tool.retry", tool="jsearch", reason=str(exc), delay_seconds=delay)
            time.sleep(delay)
    raise last_error


# ─────────────────────────────────────────────
#  Parse job from API response
# ─────────────────────────────────────────────

def _parse_job(raw: dict) -> dict:
    """Convert raw JSearch API job to clean dict."""
    # Salary
    salary = ""
    if raw.get("job_min_salary") and raw.get("job_max_salary"):
        currency = raw.get("job_salary_currency", "USD")
        period   = raw.get("job_salary_period", "YEAR")
        salary   = (str(int(raw["job_min_salary"])) + " - " +
                   str(int(raw["job_max_salary"])) + " " +
                   currency + "/" + period)

    # Location
    city    = raw.get("job_city", "")
    state   = raw.get("job_state", "")
    country = raw.get("job_country", "")
    location_parts = [p for p in [city, state, country] if p]
    location = ", ".join(location_parts)

    if raw.get("job_is_remote"):
        location = "Remote" + (" (" + country + ")" if country else "")

    return {
        "job_id":       raw.get("job_id", ""),
        "company":      raw.get("employer_name", "Unknown"),
        "position":     raw.get("job_title", ""),
        "country":      location,
        "salary_range": salary,
        "source":       raw.get("job_publisher", "JSearch"),
        "apply_link":   raw.get("job_apply_link", ""),
        "description":  (raw.get("job_description", "")[:300]
                        if raw.get("job_description") else ""),
        "employment_type": raw.get("job_employment_type", ""),
        "is_remote":    raw.get("job_is_remote", False),
        "date_posted":  raw.get("job_posted_at_datetime_utc", "")[:10]
                        if raw.get("job_posted_at_datetime_utc") else "",
        "date_found":   datetime.now().strftime("%Y-%m-%d")
    }


def _format_salary(min_s, max_s, median, currency):
    if min_s and max_s:
        return str(int(min_s)) + " - " + str(int(max_s)) + " " + currency + "/year"
    if median:
        return "~" + str(int(median)) + " " + currency + "/year"
    return "Not specified"


# ─────────────────────────────────────────────
#  Save to database
# ─────────────────────────────────────────────

def _save_jobs(jobs: list) -> int:
    """Save parsed jobs to the jobs module in database."""
    try:
        from backend.data import database, excel_manager

        saved = 0
        for job in jobs:
            record = {
                "company":      job.get("company", "Unknown"),
                "position":     job.get("position", ""),
                "country":      job.get("country", ""),
                "date_applied": datetime.now().strftime("%Y-%m-%d"),
                "source":       job.get("source", "JSearch"),
                "status":       "viewed",
                "salary_range": job.get("salary_range", ""),
                "notes":        (
                    job.get("apply_link", "") + " | " +
                    job.get("description", "")[:150]
                )
            }
            record_id = database.insert("jobs", record)
            try:
                rec = database.select_one("jobs", record_id)
                excel_manager.append_row("jobs", rec)
            except Exception:
                pass
            saved += 1

        return saved
    except Exception as e:
        print("Save error: " + str(e))
        return 0


# ─────────────────────────────────────────────
#  Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing JSearch API...\n")

    # Test 1 — Search SQA jobs in Japan
    print("Test 1: SQA jobs in Japan")
    print("-" * 40)
    result = search_jobs("SQA Engineer", "Japan", save_to_db=False)
    print("  Success : " + str(result["success"]))
    print("  Message : " + result["message"])
    for job in result["jobs"][:3]:
        print("  - " + job["position"] + " | " +
              job["company"] + " | " + job["country"])
        if job.get("salary_range"):
            print("    Salary: " + job["salary_range"])
        if job.get("apply_link"):
            print("    Apply : " + job["apply_link"][:60])

    print()

    # Test 2 — Remote jobs worldwide
    print("Test 2: Remote QA jobs worldwide")
    print("-" * 40)
    result2 = search_jobs("QA Engineer", remote_only=True, save_to_db=False)
    print("  Success : " + str(result2["success"]))
    print("  Message : " + result2["message"])
    for job in result2["jobs"][:3]:
        print("  - " + job["position"] + " | " + job["company"] + " | " + job["country"])

    print()

    # Test 3 — Salary estimate
    print("Test 3: Salary estimate for SQA Engineer in Japan")
    print("-" * 40)
    salary = get_salary_estimate("SQA Engineer", "Japan")
    print("  Success : " + str(salary["success"]))
    print("  Message : " + salary["message"])
