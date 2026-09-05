sudo apt update

# zsh
sudo apt install -y zsh
zsh --version
chsh -s $(which zsh)

# zimfw
curl -fsSL https://raw.githubusercontent.com/zimfw/install/master/install.zsh | zsh

# docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
sudo systemctl enable docker
sudo systemctl start docker
docker --version
docker compose version
