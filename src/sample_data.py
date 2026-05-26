"""
sample_data.py — Sample CV + job posting for end-to-end testing.

Used by `python main.py --demo` to run the full pipeline without needing
real files. Replace with --cv and --jobs flags for real usage.
"""

SAMPLE_CV_TEXT = """\
CHARLES DOE
Senior Software Engineer
charles@example.com | +506 8888 8888 | linkedin.com/in/charlesdoe | San José, CR

SUMMARY
Senior software engineer with 10+ years building backend systems and CI/CD
automation. Strong focus on Go, Python, and developer-experience tooling.

EXPERIENCE
Senior Software Engineer — Acme Corp (2021 — Present)
- Designed and shipped a Go package that wraps the Linux yum CLI for
  transaction history and recovery, including rpmdb repair logic.
- Led migration of internal CI from Jenkins to GitHub Actions, cutting
  build time from 22 minutes to 9 minutes.
- Mentored 3 junior engineers and ran a weekly architecture review.

Software Engineer — Beta Inc (2017 — 2021)
- Built REST APIs in Python (FastAPI) for an internal tooling platform.
- Owned the Docker base images used across 12 services.
- Collaborated with the platform team on Kubernetes rollout strategies.

Junior Developer — Gamma Studio (2014 — 2017)
- Worked on a Vue.js + Node.js dashboard used by 200+ internal users.
- Helped triage incoming bugs and contributed to the QA process.

EDUCATION
B.Sc. Computer Science — Universidad de Costa Rica (2014)

SKILLS
Go, Python, Docker, Kubernetes, GitHub Actions, Jenkins, Bash, REST APIs,
PostgreSQL, Redis, Linux administration, RPM packaging.

LANGUAGES
Spanish (native), English (professional)
"""

SAMPLE_JOB_TEXT = """\
Senior Backend Engineer (Go) — RemoteCo

About RemoteCo
We're a fast-growing fintech startup operating in 14 countries. Our backend
team is small, opinionated, and ships every day.

The Role
We're looking for a Senior Backend Engineer with deep Go experience to own
critical services in our payments stack. You'll work directly with the CTO
and have significant autonomy over architecture decisions.

Responsibilities
- Design and implement high-throughput Go services for payment processing.
- Improve observability across the platform (metrics, tracing, logging).
- Lead code reviews and mentor mid-level engineers.
- Contribute to our internal tooling — we treat dev experience as a product.
- Be on-call rotation (1 week every 6 weeks).

Must-have Requirements
- 5+ years professional Go experience.
- Production experience with Kubernetes and observability stacks
  (Prometheus, Grafana, OpenTelemetry).
- Strong communication in English (we operate async across timezones).
- Experience with PostgreSQL at scale.
- Linux command-line fluency.

Nice-to-have
- Fintech or payments domain experience.
- Open source contributions.
- Experience with gRPC and protocol buffers.
- Spanish.

What We Offer
- Fully remote, async-friendly culture.
- Competitive salary in USD.
- Equity package.
- Annual offsite (last year was Lisbon).

How We Work
- Async-first, written communication.
- No standups. Weekly written updates.
- Strong ownership culture — no babysitting.
"""

# Path placeholders — used when the user runs --demo and we generate
# temporary files on disk so that the PDF/DOCX-based tools have something
# to read.
DEMO_CV_PATH = "cv/sample_cv.docx"
DEMO_JOB_PDF_PATH = "jobs/sample_job.pdf"
