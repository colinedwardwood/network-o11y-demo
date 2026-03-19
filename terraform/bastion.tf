# ─── SSH Key Pair ─────────────────────────────────────────────────────────────

resource "tls_private_key" "bastion" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "bastion" {
  key_name   = "${local.name}-bastion"
  public_key = tls_private_key.bastion.public_key_openssh
}

# Write the private key next to the repo root — chmod 600, gitignored
resource "local_sensitive_file" "bastion_private_key" {
  content         = tls_private_key.bastion.private_key_pem
  filename        = "${path.module}/../${local.name}.pem"
  file_permission = "0600"
}

# ─── Security Group ───────────────────────────────────────────────────────────

resource "aws_security_group" "bastion" {
  name        = "${local.name}-bastion"
  description = "Bastion host - SSH inbound from operator IP only, all outbound allowed"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "SSH from operator"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name}-bastion"
  }
}

# ─── IAM Role (allows kubectl against the private EKS endpoint) ───────────────

resource "aws_iam_role" "bastion" {
  name = "${local.name}-bastion"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "bastion_eks" {
  name = "eks-access"
  role = aws_iam_role.bastion.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["eks:DescribeCluster", "eks:ListClusters"]
      Resource = "*"
    }]
  })
}

# SSM managed instance core — lets any IAM principal with ssm:StartSession
# connect via AWS SSM Session Manager without SSH keys or SG rules.
# Team members authenticate with their own AWS credentials; no .pem needed.
resource "aws_iam_role_policy_attachment" "bastion_ssm" {
  role       = aws_iam_role.bastion.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "bastion" {
  name = "${local.name}-bastion"
  role = aws_iam_role.bastion.name
}

# ─── EC2 Instance ─────────────────────────────────────────────────────────────

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "bastion" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = "t3.micro"
  subnet_id                   = module.vpc.public_subnets[0]
  associate_public_ip_address = true
  key_name                    = aws_key_pair.bastion.key_name
  vpc_security_group_ids      = [aws_security_group.bastion.id]
  iam_instance_profile        = aws_iam_instance_profile.bastion.name

  # Install kubectl and wire up kubeconfig once EKS is reachable
  user_data = base64encode(templatefile("${path.module}/templates/bastion_userdata.sh.tpl", {
    cluster_name = local.name
    aws_region   = var.aws_region
  }))

  tags = {
    Name = "${local.name}-bastion"
  }

  # Ensure EKS access entry exists before the bastion tries to authenticate
  depends_on = [aws_eks_access_entry.bastion]
}
