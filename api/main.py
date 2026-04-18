from fastapi import FastAPI

app = FastAPI()

# Nginxから /api/hello に転送されてきた場合の処理
@app.get("/api/hello")
def read_root():
    return {"message": "Hello from Python!"}

# Nginxから /api/hello に転送されてきた場合の処理
@app.get("/api/good_night")
def read_root():
    return {"message": "Good night from Python!"}
