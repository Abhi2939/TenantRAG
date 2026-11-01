import sys
from app.embed import embed_query
from app.db import connection

question = " ".join(sys.argv[1:])
q = embed_query(question)
with connection() as c:
    rows = c.execute(
        "select left(text, 200), embedding <=> %s::vector as dist "
        "from chunks order by dist limit 3",
        (str(q),),
    ).fetchall()
for text, dist in rows:
    print(round(dist, 3), text, "\n")