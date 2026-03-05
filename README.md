#  Retro Video Pipeline

Automatiza a criação de vídeos curtos (Reels/Shorts) de jogos retro a partir de longplays do YouTube. Com um único comando, o pipeline busca o vídeo, baixa trechos de gameplay, compõe o layout vertical e gera o arquivo final pronto para publicação.

---

##  Resultado final

Vídeo vertical **1080×1920** com:
- Faixa superior com título, plataforma e ano
- Gameplay centralizado (3 trechos de 5s de momentos distintos do jogo)
- Capa do jogo e imagem do console em destaque
- Informações de developer, publisher e descrição

---

##  Tecnologias utilizadas

| Categoria | Tecnologia |
|---|---|
| Linguagem | Python 3, Bash |
| Download de vídeo | `yt-dlp` |
| Processamento de vídeo | `ffmpeg`, `ffprobe` |
| Metadados de jogos | RAWG API |
| Imagens de consoles | Wikimedia Commons API |
| Remoção de fundo | `Pillow` |
| HTTP | `requests` |
| Configuração | `python-dotenv` |

---

##  Estrutura do projeto

```
retro-pipeline/
 scripts/
    setup_game.py      # Busca longplay e gera source.json automaticamente
    render.py          # Renderiza o vídeo final
 games/
    crash_bandicoot/
        source.json    # Configuração do jogo (gerada automaticamente)
 platforms/
    playstation_1.png  # Imagens dos consoles (adicionadas uma única vez)
    playstation_2.png
    ...
 tmp/                   # Arquivos intermediários (downloads, clips)
 output/                # Vídeos finais gerados
 setup_platforms.sh     # Script que cria a estrutura e baixa imagens dos consoles
 .env                   # Chaves de API
```

---

##  Instalação

### 1. Pré-requisitos

- Python 3.10+
- ffmpeg instalado e disponível no PATH

```bash
# Windows (Chocolatey)
choco install ffmpeg

# macOS
brew install ffmpeg

# Linux
sudo apt install ffmpeg
```

### 2. Clone o repositório

```bash
git clone https://github.com/seu-usuario/retro-video-pipeline.git
cd retro-video-pipeline/retro-pipeline
```

### 3. Instale as dependências Python

```bash
pip install yt-dlp requests python-dotenv Pillow
```

### 4. Configure as chaves de API

Crie um arquivo `.env` na raiz do projeto:

```env
RAWG_KEY=sua_chave_aqui
```

> Obtenha sua chave gratuita em [rawg.io/apidocs](https://rawg.io/apidocs)

### 5. Crie a estrutura de pastas e baixe as imagens dos consoles

```bash
bash setup_platforms.sh
```

Isso cria as pastas `games/`, `platforms/`, `tmp/` e `output/`, e baixa automaticamente as imagens de 15 consoles.

---

##  Uso

### Gerar um vídeo com um único comando

```bash
cd scripts
python setup_game.py "Nome do Jogo" "Plataforma"
```

**Exemplos:**

```bash
python setup_game.py "Crash Bandicoot" "PlayStation 1"
python setup_game.py "God of War" "PlayStation 2"
python setup_game.py "Super Mario World" "Super Nintendo"
python setup_game.py "Sonic the Hedgehog" "Mega Drive"
python setup_game.py "Nights into Dreams" "Sega Saturn"
```

O script executa automaticamente:

1. **RAWG**  busca metadados do jogo (dev, publisher, descrição, capa)
2. **YouTube**  encontra o melhor longplay disponível, priorizando canais especializados
3. **source.json**  gera a configuração do jogo com timestamps automáticos
4. **render.py**  baixa os trechos, corta, concatena e renderiza o vídeo final

O vídeo é salvo em `output/<slug>.mp4`.

---

##  Fluxo interno do render

```
yt-dlp    baixa 3 trechos curtos (~15s cada) em timestamps distintos
ffmpeg    corta cada trecho em 5s
ffmpeg    concatena os 3 clips (15s total)
ffmpeg    compõe layout vertical 1080×1920:
           
             Título | Plataforma | Ano     drawtext
           
                                        
                   GAMEPLAY                scale + crop
                                        
                    
               Capa       Console      overlay (alpha)
           
             Developer: ...                drawtext
             Publisher: ...             
             Description: ...           
           
output/   <slug>.mp4
```

---

##  Plataformas suportadas

| `platform_key` | Plataforma |
|---|---|
| `playstation_1` | PlayStation 1 |
| `playstation_2` | PlayStation 2 |
| `playstation_3` | PlayStation 3 |
| `nes` | Nintendo Entertainment System |
| `super_nintendo` | Super Nintendo |
| `nintendo_64` | Nintendo 64 |
| `gamecube` | GameCube |
| `mega_drive` | Sega Mega Drive / Genesis |
| `sega_saturn` | Sega Saturn |
| `sega_dreamcast` | Sega Dreamcast |
| `game_boy` | Game Boy |
| `game_boy_color` | Game Boy Color |
| `game_boy_advance` | Game Boy Advance |
| `nintendo_ds` | Nintendo DS |
| `atari_2600` | Atari 2600 |

---

##  source.json

Gerado automaticamente pelo `setup_game.py`. Pode ser editado manualmente se necessário:

```json
{
  "slug": "crash_bandicoot",
  "youtube_longplay_url": "https://www.youtube.com/watch?v=...",
  "platform_label": "PlayStation 1",
  "platform_key": "playstation_1",
  "rawg_query": "Crash Bandicoot",
  "clip_starts": ["00:14:20", "00:35:50", "00:53:45"]
}
```

| Campo | Descrição |
|---|---|
| `slug` | Identificador do jogo (nome da pasta em `games/`) |
| `youtube_longplay_url` | URL do vídeo no YouTube |
| `platform_label` | Nome exibido no vídeo |
| `platform_key` | Chave para buscar a imagem em `platforms/` |
| `rawg_query` | Termo de busca na RAWG |
| `clip_starts` | Timestamps dos 3 trechos a baixar |

---

##  Opções avançadas

### Forçar re-render sem baixar novamente

```bash
# Deleta apenas o output e rerenderiza
del output\crash_bandicoot.mp4
python render.py crash_bandicoot
```

### Forçar tudo do zero

```bash
python render.py crash_bandicoot --force
```

### Override manual de capa ou console

Coloque `cover.png` ou `console.png` diretamente na pasta do jogo  eles têm prioridade sobre os automáticos:

```
games/crash_bandicoot/
  source.json
  cover.png       override manual (opcional)
  console.png     override manual (opcional)
```

---

##  Dependências

```
yt-dlp
requests
python-dotenv
Pillow
ffmpeg (sistema)
```
