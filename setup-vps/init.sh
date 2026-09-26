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

# oracle instanceのubuntuイメージにはviが入ってなかった
sudo apt update
sudo apt install vim

# customize zsh
vi ~/.zshrc
# alias ll='ls -al'
# alias g=git
# alias d=docker
# alias dc='docker compose'

# crone github repository
mkdir ~/Projects
cd ~/Projects
git clone https://github.com/yamatatsu/cloud-workplace.git
cp .env.example .env # and write your environment variables
docker compose up -d