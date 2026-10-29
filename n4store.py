"""Lossless N4 local multidimensional store: packed 4-bit symbols, shared field-name
prototypes, optional compression, SQLite transactions and indexed dimensions.
This does NOT make Render free-tier disk durable across deployments.
"""
import hashlib,json,sqlite3,time,zlib
from pathlib import Path

MAGIC=b'N4D1'
PROTOTYPES=('buyer','capability','currency','max_budget','details','created_at',
            'expires_at','id','created_monotonic','agent_id','price',
            'expires_at_unix','contact_url')
FIELD_INDEX={key:i for i,key in enumerate(PROTOTYPES)}

def encode(record):
    if not isinstance(record,dict) or any(not isinstance(k,str) for k in record):
        raise TypeError("Expected a dict with string keys")
    folded=[[FIELD_INDEX.get(k,k),v] for k,v in sorted(record.items())]
    raw=json.dumps(folded,ensure_ascii=False,sort_keys=True,
                   separators=(',',':'),allow_nan=False).encode("utf-8")
    packed=zlib.compress(raw,9)
    body=b'Z'+packed if len(packed)<len(raw) else b'J'+raw
    # Each byte packs two exact independent N4 symbols.
    nibbles=bytes(((b>>4)<<4)|(b&15) for b in body)
    return MAGIC+hashlib.sha256(nibbles).digest()[:16]+nibbles

def decode(blob):
    if not isinstance(blob,bytes) or len(blob)<22 or blob[:4]!=MAGIC:
        raise ValueError("Invalid N4 header")
    body=blob[20:]
    if hashlib.sha256(body).digest()[:16]!=blob[4:20]:
        raise ValueError("Corrupt N4 checksum")
    if body[:1]==b'Z':raw=zlib.decompress(body[1:])
    elif body[:1]==b'J':raw=body[1:]
    else:raise ValueError("Invalid N4 codec")
    if len(raw)>65536:raise ValueError("N4 record too large")
    result={}
    for key,value in json.loads(raw.decode("utf-8")):
        key=PROTOTYPES[key] if type(key) is int and 0<=key<len(PROTOTYPES) else key
        if not isinstance(key,str) or key in result:raise ValueError("Invalid N4 prototype")
        result[key]=value
    return result

class N4Store:
    def __init__(self,path):
        self.path=str(path)
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=10,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA busy_timeout=10000')
        self.db.execute("""CREATE TABLE IF NOT EXISTS entries(
          kind TEXT NOT NULL, id TEXT NOT NULL, dimension_a TEXT NOT NULL,
          dimension_b TEXT NOT NULL, expires_at REAL NOT NULL,
          payload BLOB NOT NULL, PRIMARY KEY(kind,id))""")
        self.db.execute("CREATE INDEX IF NOT EXISTS n4_dimensions ON entries(kind,dimension_a,dimension_b,expires_at)")
        self.db.commit()

    def put(self,kind,id,record,dimension_a='',dimension_b='',expires_at=0):
        if kind not in ('need','offer','intent') or not isinstance(id,str) or not id or len(id)>128:
            raise ValueError("Invalid record identity")
        if any(not isinstance(x,str) or len(x)>128 for x in (dimension_a,dimension_b)):
            raise ValueError("Invalid dimensions")
        blob=encode(record)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?)",
                            (kind,id,dimension_a,dimension_b,float(expires_at),blob))

    def delete(self,kind,id):
        with self.db:self.db.execute("DELETE FROM entries WHERE kind=? AND id=?",(kind,id))

    def scan(self,kind,dimension_a=None,dimension_b=None,now=None):
        now=time.time() if now is None else now
        query="SELECT id,payload FROM entries WHERE kind=? AND expires_at>?"
        args=[kind,now]
        if dimension_a is not None:
            query+=" AND dimension_a=?";args.append(dimension_a)
        if dimension_b is not None:
            query+=" AND dimension_b=?";args.append(dimension_b)
        return {id:decode(blob) for id,blob in self.db.execute(query,args)}

    def purge(self,now=None):
        now=time.time() if now is None else now
        with self.db:
            return self.db.execute("DELETE FROM entries WHERE expires_at<=?",(now,)).rowcount

    def count(self,kind,now=None):
        now=time.time() if now is None else now
        return self.db.execute("SELECT count(*) FROM entries WHERE kind=? AND expires_at>?",
                               (kind,now)).fetchone()[0]

    def close(self):
        self.db.close()
