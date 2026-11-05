from app.config import settings
from app.retrieve import retrieve

print("DB:", settings.database_url.split("@")[-1])  
r = retrieve("Which database does Phase 1 use to store vectors?", 5)
print("returned:", type(r), len(r))
for c in r:
    print("---", {k: (v if k != "text" else v[:120]) for k, v in c.items()} if isinstance(c, dict) else c)