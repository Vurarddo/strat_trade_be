from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

app = FastAPI()

@app.get("/test")
def test_route(min_payout: int = Query(75, ge=0, le=100)):
    return {"min_payout": min_payout}

client = TestClient(app)
response = client.get("/test?min_payout=75.0")
print(response.status_code)
print(response.json())
