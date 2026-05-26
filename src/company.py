"""Company domain registry for career-page URL resolution.

Shared between the report renderer (links section) and the search pipeline
(company career page discovery). Extracted from main.py (Phase 3d).
"""
from __future__ import annotations

__all__ = ["KNOWN_CR_COMPANIES", "resolve_company_domain"]

KNOWN_CR_COMPANIES = {
    # Tech & semiconductor
    "intel":               "jobs.intel.com",
    "hp":                  "jobs.hp.com",
    "hpe":                 "careers.hpe.com",
    "dell":                "jobs.dell.com",
    "oracle":              "careers.oracle.com",
    "cisco":               "jobs.cisco.com",
    "vmware":              "careers.vmware.com",
    "microsoft":           "jobs.careers.microsoft.com",
    "ibm":                 "ibm.com/careers",
    "amazon":              "amazon.jobs",
    "aws":                 "amazon.jobs",
    "sap":                 "jobs.sap.com",
    "salesforce":          "careers.salesforce.com",
    "splunk":              "splunk.wd1.myworkdayjobs.com",
    "workday":             "workday.wd5.myworkdayjobs.com",
    "imprivata":           "imprivata.com/company/careers",
    "experian":            "experiancareers.com",
    # Consulting / professional services
    "accenture":           "accenture.com/cr-en/careers",
    "deloitte":            "apply.deloitte.com",
    "pwc":                 "jobs.pwc.com",
    "ey":                  "careers.ey.com",
    "kpmg":                "kpmg.com/jobs",
    "cognizant":           "careers.cognizant.com",
    "capgemini":           "capgemini.com/careers",
    "genpact":             "careers.genpact.com",
    "dxc":                 "careers.dxc.com",
    "ntt data":            "us.nttdata.com/en/careers",
    # Finance / insurance / data
    "equifax":             "careers.equifax.com",
    "moody's":             "careers.moodys.com",
    "moodys":              "careers.moodys.com",
    "citi":                "jobs.citi.com",
    "citibank":            "jobs.citi.com",
    "bank of america":     "careers.bankofamerica.com",
    "western union":       "careers.westernunion.com",
    "jll":                 "jll.referrals.selectminds.com",
    # Consumer / industrial
    "p&g":                 "pgcareers.com",
    "procter & gamble":    "pgcareers.com",
    "coca-cola":           "careers.coca-colacompany.com",
    "3m":                  "careers.3m.com",
    "emerson":             "jobs.emerson.com",
    "honeywell":           "careers.honeywell.com",
    "siemens":             "jobs.siemens.com",
    "schneider electric":  "careers.se.com",
    "bosch":               "smartrecruiters.com/BoschGroup",
    "bayer":               "career.bayer.com",
    # Med-tech / pharma
    "boston scientific":   "jobs.bostonscientific.com",
    "abbott":              "jobs.abbott",
    "edwards lifesciences": "jobs.edwards.com",
    "philips":             "philips.com/a-w/careers",
    "amgen":               "careers.amgen.com",
    "smith & nephew":      "careers.smith-nephew.com",
    "establishment labs":  "establishmentlabs.com/careers",
    # BPO / services
    "concentrix":          "jobs.concentrix.com",
    "taskus":              "taskus.com/careers",
    "auxis":               "auxis.com/careers",
}


def resolve_company_domain(name: str) -> str | None:
    """Resolve a company name (case-insensitive) to its careers domain."""
    return KNOWN_CR_COMPANIES.get(name.strip().lower())
