#!/usr/bin/env bash

set -e

echo "=============================="
echo "Retro Video Pipeline Setup"
echo "=============================="

echo ""
echo "Checking Python..."

if command -v python3 >/dev/null 2>&1; then
    PY_VERSION=$(python3 --version)
    echo "Python detected: $PY_VERSION"
else
    echo "Python not found. Installing..."
    
    if command -v apt >/dev/null 2>&1; then
        sudo apt update
        sudo apt install -y python3 python3-pip python3-venv
    elif command -v brew >/dev/null 2>&1; then
        brew install python
    else
        echo "Package manager not supported. Install Python manually."
        exit 1
    fi
fi

echo ""
echo "Installing yt-dlp..."

if command -v yt-dlp >/dev/null 2>&1; then
    echo "yt-dlp already installed"
else
    if command -v apt >/dev/null 2>&1; then
        sudo apt install -y yt-dlp
    elif command -v brew >/dev/null 2>&1; then
        brew install yt-dlp
    else
        pip3 install -U yt-dlp
    fi
fi

echo ""
echo "Installing FFmpeg..."

if command -v ffmpeg >/dev/null 2>&1; then
    echo "FFmpeg already installed"
else
    if command -v apt >/dev/null 2>&1; then
        sudo apt install -y ffmpeg
    elif command -v brew >/dev/null 2>&1; then
        brew install ffmpeg
    else
        echo "Please install ffmpeg manually"
        exit 1
    fi
fi

echo ""
echo "Installing ImageMagick (optional)..."

if command -v convert >/dev/null 2>&1; then
    echo "ImageMagick already installed"
else
    if command -v apt >/dev/null 2>&1; then
        sudo apt install -y imagemagick
    elif command -v brew >/dev/null 2>&1; then
        brew install imagemagick
    else
        echo "Skipping ImageMagick install"
    fi
fi

echo ""
echo "Creating Python virtual environment..."

python3 -m venv venv

source venv/bin/activate

echo ""
echo "Installing Python dependencies..."

pip install --upgrade pip

pip install \
    requests \
    moviepy \
    ffmpeg-python \
    python-dotenv

echo ""
echo "Setup complete!"

echo ""
echo "Activate environment with:"
echo "source venv/bin/activate"
