# EC2 g6.xlarge + Debian 13 + Ollama + Code Investigation Agent

[EC2 sizing](#ec2-sizing) · [Launch](#launch) · [GPU driver](#gpu-driver) · [Ollama](#ollama) · [Agent](#agent) · [Benchmarks](#benchmarks) · [Cost and security](#cost-and-security)

## EC2 sizing

- Region: Asia Pacific (Tokyo), \`ap-northeast-1\`.
- Instance: \`g6.xlarge\`, x86_64, 4 vCPU, 16 GiB RAM, NVIDIA L4 (24 GB GPU memory). Do not accidentally select \`g6f.xlarge\`, which provides only a fraction of an L4.
- OS: official Debian 13 (Trixie) amd64 AMI; confirm AMI publisher, architecture, and EC2 GPU/instance compatibility.
- Boot storage: 100 GiB EBS gp3, encrypted. Do not place durable models or results on instance-store NVMe: it is erased on stop.
- Security group: inbound TCP 22 from **your own public IP/32 only**; no inbound 11434. Do not open SSH to 0.0.0.0/0.
- EC2 quotas: verify "Running On-Demand G and VT instances" >= 4 vCPUs in ap-northeast-1 before launch. If 0, request increase.
- Key pair: create or choose EC2 .pem key, keep private key local. EC2 Debian default login is \`admin\`.

## Launch

From Windows PowerShell, after the EC2 console reports "running" and has a public IPv4 address:

\`\`\`powershell
ssh -i "$HOME\Downloads\gpu-key.pem" admin@<EC2_PUBLIC_IP>
\`\`\`

Use the matching key filename and actual EC2 address; angle-bracket values are placeholders.

## GPU driver

Debian 13's Debian-packaged NVIDIA driver branch supports Ada L4 but its 550 branch has known security-maintenance concerns as of Oct 2026. For long-running/untrusted production environments, prefer a supported, patched NVIDIA compute driver following the AWS driver guide; do not blindly run vendor installation scripts. Use this apt path only after reviewing security status and apt candidate version.

\`\`\`bash
sudo apt update
sudo apt install -y git curl ca-certificates pciutils python3 python3-venv \
  python3-pip sqlite3 tmux build-essential dkms linux-headers-$(uname -r)
lspci | grep -i nvidia
cat /etc/os-release
grep -R '^Components:' /etc/apt/sources.list.d/ || true
\`\`\`

Enable \`contrib non-free non-free-firmware\` in the official Debian repositories if they are missing. On the default Debian 13 deb822 layout, verify \`/etc/apt/sources.list.d/debian.sources\` and edit its \`Components:\` lines as needed, rather than adding duplicate repositories.

\`\`\`bash
sudo apt update
apt-cache policy nvidia-driver
sudo apt install -y nvidia-driver
sudo reboot
\`\`\`

SSH back in, then:

\`\`\`bash
nvidia-smi
\`\`\`

**Stop here unless \`nvidia-smi\` lists NVIDIA L4 and a working driver.** If DKMS fails, inspect \`journalctl -k\`, \`dkms status\`, kernel headers, Secure Boot policy and \`nouveau\`. Do not install conflicting NVIDIA drivers on top of an existing driver.

Sources:
- https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/install-nvidia-driver.html
- https://wiki.debian.org/NvidiaGraphicsDrivers/
- https://packages.debian.org/trixie/nvidia-driver-full

## Ollama

\`\`\`bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
ollama --version
ollama pull qwen3:8b
ollama run qwen3:8b "Respond briefly to this test"
ollama ps
nvidia-smi
\`\`\`

\`ollama ps\` should report \`100% GPU\` for a model fitting in L4 VRAM. Check \`sudo journalctl -u ollama -n 100 --no-pager\` if the model is on CPU. Ollama serves on 127.0.0.1 by default. Do not publicly expose the service without authentication and network protection.

Sources:
- https://github.com/ollama/ollama/blob/main/docs/linux.mdx
- https://github.com/ollama/ollama/blob/main/docs/gpu.mdx

## Agent

\`\`\`bash
git clone https://github.com/v-h-giang/Local-AI-Code-Investigation-Agent.git
cd Local-AI-Code-Investigation-Agent
python3 -m venv .venv
source .venv/bin/activate
python --version
python -m unittest discover -s tests -v
python -m unittest discover -s benchmark/tests -v
python benchmark/run.py --preflight
\`\`\`

The Python application is written against the standard library. The Windows \`setup.ps1\` is not used on Debian. Optional Tree-sitter parsers can be installed separately after a passing standard-library baseline; avoid changing the retrieval configuration when comparing two benchmark runs.

## Benchmarks

Three-case smoke test from the repository root:

\`\`\`bash
python benchmark/run.py \
  --suite repocontextbench --mode ai --fetch-repos \
  --run-id retrieval_v5_debian_smoke --llm-timeout 600 \
  --case-id repo_context_bench_agent_framework_practical_0001 \
  --case-id repo_context_bench_agent_framework_practical_0011 \
  --case-id repo_context_bench_agent_framework_practical_0018
\`\`\`

For a long run disconnecting from SSH must not stop the benchmark. Use tmux:

\`\`\`bash
tmux new -s bench
python benchmark/run.py --suite all --mode ai --fetch-repos \
  --run-id retrieval_v5_debian_30 --llm-timeout 600 2>&1 | tee benchmark-v5.log
\`\`\`

Detach with Ctrl+B then D; return with \`tmux attach -t bench\`.

Inspect: \`cat benchmark/results/retrieval_v5_debian_30/summary.json\`.

The pre-existing benchmark baseline was 30/30 successful and 4.04% gold-span recall for all 30 tasks. Different three-case subset percentages are NOT directly comparable to the full suite.

## Cost and security

- Check the current hourly price in the AWS console before launch. Tokyo Linux On-Demand \`g6.xlarge\` was approximately USD 1.1672/hour at the 2026-10-29 price observation, excluding EBS, public IPv4, transfer and tax.
- Set a billing budget alert before launching; it not automatically stop EC2.
- **Stop** the EC2 instance when idle. EBS still costs money while stopped.
- The \`g6.xlarge\` instance store is ephemeral and erased when stopped. Store the repo, Ollama model and results on the gp3 EBS root volume.
- If no longer required, terminate the instance deliberately and check remaining EBS volumes, snapshots and Elastic IPs.

Sources:
- https://aws.amazon.com/ec2/instance-types/accelerated-computing/
- https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html
- https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-store-lifetime.html
- https://compute.info/vm/aws/g6-xlarge/
