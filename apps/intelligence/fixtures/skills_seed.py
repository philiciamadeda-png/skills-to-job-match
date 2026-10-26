# Skill seed data — loaded via: python manage.py seed_skills
# Format: canonical name, category, [aliases...]

SKILLS = [
    # Databases
    ("PostgreSQL", "database", ["Postgres", "postgres", "PostgresQL", "psql"]),
    ("MySQL", "database", ["mysql", "My SQL"]),
    ("MongoDB", "database", ["mongo", "Mongo DB"]),
    ("Redis", "database", ["redis cache"]),
    ("Elasticsearch", "database", ["elastic search", "ES", "ELK"]),
    ("SQLite", "database", ["sqlite3"]),

    # Languages
    ("Python", "language", ["python3", "Python 3", "py"]),
    ("JavaScript", "language", ["JS", "Javascript", "java script"]),
    ("TypeScript", "language", ["TS", "Typescript"]),
    ("Go", "language", ["Golang", "golang"]),
    ("Rust", "language", ["rust-lang"]),
    ("Java", "language", ["Java 17", "Java 11", "Java 8"]),
    ("C#", "language", ["csharp", "c sharp", "dotnet c#"]),
    ("Ruby", "language", ["ruby lang"]),
    ("PHP", "language", ["php8", "php7"]),

    # Frameworks
    ("Django", "framework", ["django rest framework", "DRF"]),
    ("FastAPI", "framework", ["fast api"]),
    ("React", "framework", ["ReactJS", "React.js"]),
    ("Node.js", "framework", ["NodeJS", "Node", "node js"]),
    ("Spring Boot", "framework", ["Spring", "spring framework"]),

    # Cloud / Infra
    ("AWS", "cloud", ["Amazon Web Services", "amazon aws"]),
    ("GCP", "cloud", ["Google Cloud", "Google Cloud Platform"]),
    ("Azure", "cloud", ["Microsoft Azure", "MS Azure"]),
    ("Docker", "infrastructure", ["docker container", "dockerfile"]),
    ("Kubernetes", "infrastructure", ["K8s", "k8s", "kube"]),
    ("Terraform", "infrastructure", ["tf", "terraform iac"]),

    # Data / ML
    ("Apache Kafka", "data", ["Kafka", "kafka streams"]),
    ("Apache Spark", "data", ["Spark", "PySpark", "pyspark"]),
    ("dbt", "data", ["data build tool", "DBT"]),
]
