import sys
from core.job_runner import JobRunner
from core.config_loader import load_jobs


def main(job_name=None):

    jobs, inactive_jobs = load_jobs()
    runner = JobRunner()

    if job_name:

        job = next((j for j in jobs if j["name"] == job_name), None)

        if not job:
            if job_name in inactive_jobs:
                raise ValueError(f"Job '{job_name}' exists but is inactive (active: false)")
            raise ValueError(f"Job not found: {job_name}")

        runner.run(job)

    else:
        for job in jobs:
            runner.run(job)


if __name__ == "__main__":

    job_name = sys.argv[1] if len(sys.argv) > 1 else None
    main(job_name)
