import hashlib
import os
import factory
from apps.intelligence.models import Company, Location, Job
from apps.ingestion.models import RawJobPayload


def _random_hash():
    return hashlib.sha256(os.urandom(8)).hexdigest()


class CompanyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Company

    name = factory.Sequence(lambda n: f"Company {n}")
    normalised_name = factory.Sequence(lambda n: f"company-{n}")


class LocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Location

    raw_text = "Remote"
    is_remote = True


class JobFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Job

    title = factory.Sequence(lambda n: f"Job {n}")
    source = "remotive"
    source_id = factory.Sequence(lambda n: str(n))
    content_hash = factory.LazyFunction(_random_hash)
    company = factory.SubFactory(CompanyFactory)
    location = factory.SubFactory(LocationFactory)


class RawJobPayloadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RawJobPayload

    source = "remotive"
    raw_data = {"id": 1, "title": "Test Job"}
    content_hash = factory.LazyFunction(_random_hash)
    fetched_at = factory.Faker("date_time_this_year", tzinfo=__import__("datetime").timezone.utc)
