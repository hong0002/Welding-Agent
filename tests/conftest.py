from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.main import create_app


def png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "storage")


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def scene_bytes():
    return png_bytes(Image.new("RGB", (160, 90), (50, 80, 100)))


@pytest.fixture
def mask_bytes():
    image = Image.new("L", (160, 90), 0)
    ImageDraw.Draw(image).line([(20, 50), (60, 25), (110, 60), (140, 45)], fill=255, width=9)
    return png_bytes(image)


@pytest.fixture
def scene_job(client, scene_bytes):
    response = client.post("/api/scenes/upload", files={"file": ("scene.png", scene_bytes, "image/png")})
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def mask_job(client, scene_job, mask_bytes):
    response = client.post("/api/masks/manual", data={"job_id": scene_job["id"]}, files={"file": ("mask.png", mask_bytes, "image/png")})
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def instructed_job(client, mask_job):
    response = client.post("/api/instructions/parse", json={"job_id": mask_job["id"], "instruction": "왼쪽에서 오른쪽으로 용접해"})
    assert response.status_code == 200
    return response.json()
