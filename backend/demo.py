from .models import Job, Profile


def demo_profile():
    return Profile(
        name="Alex Morgan",
        headline="Computer science student · Building thoughtful things with AI",
        summary="This sample profile combines Python, React, and machine learning projects, with an interest in useful AI products.",
        skills=["Python", "React", "Machine Learning", "SQL", "LangGraph"],
        post_themes=["Applied AI projects", "Learning in public"],
        suggested_roles=["AI Engineering Intern", "Software Engineering Intern"],
        domain="AI & Machine Learning",
        location="India / Remote",
        kind="Both",
        evidence_note="Illustrative demo profile and opportunities. No LinkedIn profile was accessed.",
    ).model_dump()


def demo_jobs(sources, kind):
    samples = [
        ("AI Engineering Intern", "Lumen Labs", "Remote", "Internship", "Unstop", ["Python", "LangGraph"], 96, "Builds on your Python and agent-workflow projects."),
        ("Machine Learning Intern", "Orbit Studio", "Bengaluru, India", "Internship", "Internshala", ["Python", "Machine Learning"], 92, "A natural next step for your hands-on machine learning experience."),
        ("Junior Frontend Engineer", "Forma", "Remote", "Job", "LinkedIn", ["React", "JavaScript"], 87, "Your React projects are relevant; strengthen production testing skills."),
        ("AI Product Engineering Intern", "Bloom AI", "Hyderabad, India", "Internship", "Wellfound", ["Python", "React"], 90, "Combines your frontend interests with practical AI development."),
    ]
    from .models import SOURCES
    return [
        Job(id=f"demo-{i}", title=t, company=c, location=l, kind=k, source=s,
            url=f"https://{SOURCES[s]}", skills=skills, match_score=score, reason=reason,
            description="Sample opportunity for exploring the interface.",
            availability="Demo only • fictional opportunity").model_dump()
        for i, (t, c, l, k, s, skills, score, reason) in enumerate(samples)
        if s in sources and (kind == "Both" or (kind == "Internships") == (k == "Internship"))
    ]
