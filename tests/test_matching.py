from backend.matching import classify, match_job
from backend.cv_parser import parse_cv
import pytest

def test_mentions_are_evidence_not_decisions():
    result = match_job("Used Python, Kubernetes and Docker on production projects.", ["Python","Kubernetes","SQL"])
    assert [x["skill"] for x in result["mentioned_skills"]] == ["Python","Kubernetes"]
    assert result["not_mentioned_skills"] == ["SQL"]
    assert result["automated_hiring_decision"] is None

def test_classification():
    families = [x["family"] for x in classify("Experience with React and TypeScript; Python APIs")]
    assert "Frontend" in families and "Backend" in families

def test_parse_text():
    assert "Kubernetes" in parse_cv("cv.txt", b"Worked with Kubernetes")

def test_reject_bad_extension():
    with pytest.raises(ValueError):
        parse_cv("payload.exe",b"invalid")
