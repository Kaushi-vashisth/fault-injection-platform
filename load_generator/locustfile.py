import random, time
from locust import HttpUser, task, between

class PlatformUser(HttpUser):
    wait_time = between(0.5, 1.5)
    host = "http://localhost:8000"

    @task
    def process_request(self):
        payload = {
            "user_id": random.randint(1, 100),
            "operation": random.choice(["read", "write"]),
            "data_size": random.randint(10, 100)
        }
        with self.client.post(
            "/process",
            json=payload,
            catch_response=True
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Status: {resp.status_code}")