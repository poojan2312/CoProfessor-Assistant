import httpx
import logging
import urllib.parse
from sqlalchemy.orm import Session
from app.models import Source, Course

log = logging.getLogger(__name__)

def verify_and_add_resources(db: Session, course: Course, resources: list[dict]) -> list[str]:
    """Verify suggested resources against external catalogues and add valid ones as 'pending'."""
    added = []
    
    for res in resources:
        kind = res.get("kind")
        identifier = res.get("identifier")
        title = res.get("title", "")
        
        if not kind or not identifier:
            continue
            
        is_valid = False
        authors = res.get("authors", "")
        year = None
        
        try:
            if kind == "book":
                # Verify via Open Library ISBN
                # Identifier should be ISBN
                isbn = ''.join(filter(str.isdigit, identifier))
                if isbn:
                    resp = httpx.get(f"https://openlibrary.org/isbn/{isbn}.json", timeout=5.0)
                    if resp.status_code == 200:
                        is_valid = True
                        data = resp.json()
                        title = data.get("title", title)
                        if "publish_date" in data:
                            try:
                                year = int(data["publish_date"][-4:])
                            except ValueError:
                                pass
            elif kind == "paper":
                # Verify via Crossref DOI
                doi = identifier.replace("https://doi.org/", "")
                resp = httpx.get(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}", timeout=5.0)
                if resp.status_code == 200:
                    is_valid = True
                    data = resp.json().get("message", {})
                    title = data.get("title", [title])[0]
            elif kind == "video":
                # Verify via YouTube oEmbed
                url = identifier
                if "youtube.com" not in url and "youtu.be" not in url:
                    url = f"https://www.youtube.com/watch?v={identifier}"
                resp = httpx.get(f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json", timeout=5.0)
                if resp.status_code == 200:
                    is_valid = True
                    data = resp.json()
                    title = data.get("title", title)
                    authors = data.get("author_name", authors)
            elif kind == "web":
                # Just a basic HEAD request to check if the URL exists
                resp = httpx.head(identifier, timeout=5.0, follow_redirects=True)
                if resp.status_code < 400:
                    is_valid = True
        except Exception as e:
            log.warning("Failed to verify resource %s: %s", identifier, e)
            
        if is_valid:
            # Check if already exists
            existing = db.query(Source).filter_by(course_id=course.id, identifier=identifier).first()
            if not existing:
                source = Source(
                    course_id=course.id,
                    kind=kind,
                    title=title,
                    authors=authors,
                    year=year,
                    identifier=identifier,
                    status="pending",
                    allowed_uses=["lecture_content"]
                )
                db.add(source)
                added.append(f"{title} ({identifier})")
    
    db.commit()
    return added
