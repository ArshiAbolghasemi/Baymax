"""The embedding and vector-store clients, against fakes of their backends."""

import uuid

import pytest

from hiro.clients.embedding import EmbeddingClient, EmbeddingError
from hiro.clients.vector_store import VectorStore


class FakeEmbeddings:
    """Mimics ``client.embeddings`` — including returning results out of order."""

    def __init__(self, dimensions=4, shuffle=False, drop=0):
        self.dimensions, self.shuffle, self.drop = dimensions, shuffle, drop
        self.batches: list[list[str]] = []

    def create(self, *, model, input):
        self.batches.append(list(input))
        data = [
            type("Item", (), {"index": i, "embedding": [float(i)] * self.dimensions})
            for i in range(len(input) - self.drop)
        ]
        if self.shuffle:
            data = list(reversed(data))
        return type("Response", (), {"data": data})


def client(**kwargs) -> EmbeddingClient:
    embedder = EmbeddingClient(
        base_url="http://embeddings.invalid/v1",
        api_key="not-needed",
        model="bge-m3",
        timeout=1,
        max_retries=0,
        batch_size=kwargs.pop("batch_size", 2),
        dimensions=kwargs.pop("dimensions", 4),
    )
    embedder._client = type("C", (), {"embeddings": kwargs.pop("embeddings", FakeEmbeddings())})()
    return embedder


class TestEmbedding:
    def test_no_texts_is_no_work(self):
        fake = FakeEmbeddings()
        assert client(embeddings=fake).embed([]) == []
        assert fake.batches == []

    def test_texts_are_sent_in_batches(self):
        fake = FakeEmbeddings()
        vectors = client(embeddings=fake, batch_size=2).embed(["a", "b", "c"])
        assert [len(batch) for batch in fake.batches] == [2, 1]
        assert len(vectors) == 3

    def test_input_order_is_preserved_even_when_the_server_reorders(self):
        """The spec allows results out of order; the caller depends on order."""
        fake = FakeEmbeddings(shuffle=True)
        vectors = client(embeddings=fake, batch_size=3).embed(["a", "b", "c"])
        assert [vector[0] for vector in vectors] == [0.0, 1.0, 2.0]

    def test_a_short_response_is_an_error(self):
        with pytest.raises(EmbeddingError, match="expected 2 embeddings"):
            client(embeddings=FakeEmbeddings(drop=1), batch_size=8).embed(["a", "b"])

    def test_a_model_of_the_wrong_width_is_an_error(self):
        """Otherwise this fails much later, inside Qdrant, far less clearly."""
        with pytest.raises(EmbeddingError, match="EMBEDDING_DIMENSIONS"):
            client(embeddings=FakeEmbeddings(dimensions=8), dimensions=4).embed(["a"])


class FakeQdrant:
    def __init__(self, exists=True, points=None):
        self.exists = exists
        self.points = points or []
        self.created: list[str] = []
        self.upserted: list[list] = []
        self.deleted: list[list] = []

    def collection_exists(self, name):
        return self.exists

    def create_collection(self, *, collection_name, vectors_config):
        self.created.append(collection_name)

    def upsert(self, *, collection_name, points, wait):
        self.upserted.append(points)

    def delete(self, *, collection_name, points_selector, wait):
        self.deleted.append(points_selector)

    def query_points(self, *, collection_name, query, limit, with_payload):
        return type("R", (), {"points": self.points[:limit]})


def store(client: FakeQdrant) -> VectorStore:
    from qdrant_client.models import Distance

    return VectorStore(client, collection="test", vector_size=4, distance=Distance.COSINE)


class TestVectorStore:
    def test_a_missing_collection_is_created(self):
        fake = FakeQdrant(exists=False)
        store(fake).ensure_collection()
        assert fake.created == ["test"]

    def test_an_existing_collection_is_left_alone(self):
        fake = FakeQdrant(exists=True)
        store(fake).ensure_collection()
        assert fake.created == []

    def test_upserting_nothing_touches_the_server(self):
        fake = FakeQdrant()
        store(fake).upsert([])
        assert fake.upserted == []

    def test_search_returns_plain_dicts(self):
        """Callers and prompts must not depend on the client library's types."""
        point = type("P", (), {"score": 0.9, "payload": {"answer": "a doc"}})
        results = store(FakeQdrant(points=[point])).search([0.1] * 4, limit=5)
        assert results == [{"score": 0.9, "answer": "a doc"}]

    def test_a_point_without_payload_still_returns_its_score(self):
        point = type("P", (), {"score": 0.5, "payload": None})
        assert store(FakeQdrant(points=[point])).search([0.1] * 4) == [{"score": 0.5}]

    def test_deleting_nothing_touches_the_server(self):
        fake = FakeQdrant()
        store(fake).delete([])
        assert fake.deleted == []

    def test_deleted_points_are_sent_as_strings(self):
        fake = FakeQdrant()
        point_uid = uuid.uuid4()
        store(fake).delete([point_uid])
        assert fake.deleted == [[str(point_uid)]]
