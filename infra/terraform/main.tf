terraform {
  required_version = ">= 1.7"
  backend "s3" {
    bucket = "parcelwise-tfstate"
    key    = "prod/terraform.tfstate"
    region = "us-west-2"
  }
}

module "db" {
  source         = "./modules/postgres"
  name           = "parcelwise-prod"
  instance_class = "db.t4g.medium"
  storage_gb     = 100
}

resource "aws_s3_bucket" "labels" {
  bucket = "parcelwise-labels-prod"
}

resource "aws_s3_bucket_lifecycle_configuration" "labels" {
  bucket = aws_s3_bucket.labels.id
  rule {
    id     = "expire-pdfs"
    status = "Enabled"
    expiration { days = 90 }
  }
}
