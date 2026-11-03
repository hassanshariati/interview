"""Deterministic CV skill evidence discovery, NOT a hiring score or competence test."""
import re

FAMILIES = {
    "DevOps / SRE": ["kubernetes", "docker", "terraform", "ansible", "prometheus", "linux", "helm", "ci/cd"],
    "Backend": ["python", "java", "spring", "fastapi", "django", "node.js", "rest api", "postgresql"],
    "Data": ["sql", "spark", "pandas", "airflow", "machine learning", "etl", "power bi"],
    "Security": ["siem", "soc", "penetration testing", "owasp", "firewall", "zero trust"],
    "Frontend": ["react", "typescript", "javascript", "next.js", "css", "html"],
}

def find_skill_mentions(text: str, skills: list[str]) -> dict[str, str]:
    result = {}
    for skill in skills:
        skill = skill.strip()
        if not skill:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", re.I)
        match = pattern.search(text)
        if match:
            start = max(0, match.start()-65)
            end = min(len(text), match.end()+65)
            result[skill] = text[start:end].replace("\n", " ").strip()
    return result

def classify(text: str) -> list[dict]:
    categories = []
    for family, skills in FAMILIES.items():
        evidence = find_skill_mentions(text, skills)
        if evidence:
            categories.append({"family":family, "mentioned_skills":list(evidence)})
    return categories

def match_job(text: str, skills: list[str]) -> dict:
    evidence = find_skill_mentions(text, skills)
    missing = [skill for skill in skills if skill.strip() and skill not in evidence]
    return {
        "mentioned_skills": [{"skill":k, "cv_excerpt":v} for k, v in evidence.items()],
        "not_mentioned_skills": missing,
        "message": "Mentions in a CV are not proof of competence. Missing mentions are not proof of inability. Requires human review.",
        "automated_hiring_decision": None,
    }
