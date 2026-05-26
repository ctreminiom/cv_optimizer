# cv/

Place your master CV here (PDF or DOCX). Real CVs are gitignored — only the synthetic `sample_cv.pdf` ships with the repo.

```
cv/
├── sample_cv.pdf          # synthetic, shipped with repo
└── <your_name>.pdf        # gitignored
```

To run the pipeline against your CV:

```bash
cv-optimizer run --cv cv/your_name.pdf --job jobs/some_posting.md
```
