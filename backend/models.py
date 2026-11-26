import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator


SOURCES = {
    "LinkedIn": "linkedin.com",
    "Unstop": "unstop.com",
    "Internshala": "internshala.com",
    "Wellfound": "wellfound.com",
}


class SearchRequest(BaseModel):
    prompt: str = Field(default="", max_length=3000)
    linkedin_url: str = Field(default="", max_length=500)
    profile_text: str = Field(default="", max_length=18000)
    domain: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=120)
    kind: Literal["Both", "Internships", "Jobs"] = "Both"
    sources: list[Literal["LinkedIn", "Unstop", "Internshala", "Wellfound"]] = Field(
        default_factory=lambda: list(SOURCES), min_length=1
    )
    demo: bool = False

    @model_validator(mode="after")
    def validate_profile(self):
        if not self.linkedin_url:
            match = re.search(r"https://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%\-]+/?", self.prompt)
            if match:
                self.linkedin_url = match.group(0)
        if self.linkedin_url:
            parsed = urlparse(self.linkedin_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in {"linkedin.com", "www.linkedin.com"}
                or parsed.username or parsed.password or parsed.port
                or not re.fullmatch(r"/in/[A-Za-z0-9_%\-]+/?", parsed.path)
                or parsed.query or parsed.fragment
            ):
                raise ValueError("Use a LinkedIn profile URL like https://www.linkedin.com/in/your-name/")
        if not self.demo and not any((self.linkedin_url, self.profile_text.strip(), self.prompt.strip(), self.domain.strip())):
            raise ValueError("Add your LinkedIn profile, skills, or a description of your ideal role.")
        self.sources = list(dict.fromkeys(self.sources))
        return self


class Profile(BaseModel):
    name: str = "Your profile"
    headline: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list, max_length=20)
    post_themes: list[str] = Field(default_factory=list, max_length=8)
    suggested_roles: list[str] = Field(default_factory=list, max_length=4)
    domain: str = ""
    location: str = ""
    kind: Literal["Both", "Internships", "Jobs"] = "Both"
    evidence_note: str = ""


class Job(BaseModel):
    id: str
    title: str
    company: str = "Company not listed"
    location: str = "Location not listed"
    kind: Literal["Job", "Internship", "Unspecified"] = "Unspecified"
    source: str
    url: str
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    match_score: int = Field(default=0, ge=0, le=100)
    reason: str = ""
    salary: str = "Not listed"
    availability: str = "Search-index result • verify on source"


class Assessment(BaseModel):
    candidate_id: str
    is_job_listing: bool
    matches_preferences: bool = True
    title: str
    company: str = "Company not listed"
    location: str = "Location not listed"
    kind: Literal["Job", "Internship", "Unspecified"] = "Unspecified"
    skills: list[str] = Field(default_factory=list, max_length=10)
    match_score: int = Field(ge=0, le=100)
    reason: str
    salary: str = "Not listed"


class Assessments(BaseModel):
    jobs: list[Assessment]


class FriendlySummary(BaseModel):
    message: str
    next_steps: list[str] = Field(default_factory=list, max_length=4)
