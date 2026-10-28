"""Small atomic JSON files with durable replacement and no partial publication."""
import json, os, uuid

def atomic_json(path, value):
    temporary=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with temporary.open("x",encoding="utf-8") as stream:
            json.dump(value,stream,ensure_ascii=False,allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        if os.name=="posix":
            fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    finally:temporary.unlink(missing_ok=True)
