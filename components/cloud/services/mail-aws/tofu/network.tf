data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "mail" {
  cidr_block           = "10.90.0.0/24"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "stalwart-mail" }
}

resource "aws_internet_gateway" "mail" {
  vpc_id = aws_vpc.mail.id
  tags   = { Name = "stalwart-mail" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.mail.id
  availability_zone       = data.aws_availability_zones.available.names[0]
  cidr_block              = "10.90.0.0/26"
  map_public_ip_on_launch = false

  tags = { Name = "stalwart-mail-public" }
}

resource "aws_subnet" "database" {
  for_each = {
    a = {
      availability_zone = data.aws_availability_zones.available.names[0]
      cidr_block        = "10.90.0.64/27"
    }
    b = {
      availability_zone = data.aws_availability_zones.available.names[1]
      cidr_block        = "10.90.0.96/27"
    }
  }

  vpc_id            = aws_vpc.mail.id
  availability_zone = each.value.availability_zone
  cidr_block        = each.value.cidr_block

  tags = { Name = "stalwart-mail-database-${each.key}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.mail.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.mail.id
  }

  tags = { Name = "stalwart-mail-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "mail" {
  name        = "stalwart-mail"
  description = "Public mail protocols; administration uses SSM"
  vpc_id      = aws_vpc.mail.id

  dynamic "ingress" {
    for_each = toset([25, 443, 465, 587, 993])
    content {
      description = "Stalwart TCP ${ingress.value}"
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  egress {
    description = "Package, AWS API, ACME, DNS, and outbound relay access"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "stalwart-mail" }
}

resource "aws_security_group" "database" {
  name        = "stalwart-mail-database"
  description = "PostgreSQL only from the Stalwart instance"
  vpc_id      = aws_vpc.mail.id

  ingress {
    description     = "PostgreSQL from Stalwart"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.mail.id]
  }

  egress {
    description = "RDS managed service egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "stalwart-mail-database" }
}
