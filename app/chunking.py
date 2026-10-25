"Pure text chunking, no I/O"

def chunk_text(text:str,chunk_size: int,overlap:int) -> list[str]:

    if chunk_size<=0:
        raise ValueError("Chunk size must be positive")

    if not 0<= overlap< chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    words = text.split()

    if not words:
        return []

    step = chunk_size - overlap
    chunks = []

    for start in range(0,len(words),step):
        window = words[start:start+chunk_size]
        chunks.append("".join(window))

        if start + chunk_size >= len(words):
            break

    return chunks