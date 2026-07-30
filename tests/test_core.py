from core.models import Job, JobStatus


def test_job_model_creation():
    job = Job(
        title="Software Engineer",
        company="Tech Corp",
        location="Remote",
        experience="0-2 years",
        salary="100k",
        url="https://example.com/job/1",
        source="LinkedIn",
        description="Great job",
        requirements="Python",
        skills="Python, SQL",
        posted_date="2024-01-01",
        discovered_date="2024-01-02"
    )
    assert job.title == "Software Engineer"
    assert job.company == "Tech Corp"
    assert job.url == "https://example.com/job/1"

def test_job_model_default_status():
    job = Job(
        title="Software Engineer",
        company="Tech Corp",
        location="Remote",
        experience="0-2 years",
        salary="100k",
        url="https://example.com/job/2",
        source="Indeed",
        description="",
        requirements="",
        skills="",
        posted_date="",
        discovered_date=""
    )
    assert job.status == JobStatus.NEW
