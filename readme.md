# jacu.ia monitor (beta 0.56)

> Gadget / HUD moderno e ultraleve para Windows 11 desenvolvido em Python (PyQt6) para monitoramento em tempo real de servidores, portas e endpoints.

---

## ⚡ Principais Recursos

- **Modo Gadget / HUD Always-On-Top**: Pode ficar flutuando e fixado sobre qualquer janela de jogos, IDEs ou navegadores no Windows 11.
- **Alertas Sonoros com MP3 (UP & DOWN)**:
  - Toca arquivos `.mp3` configuráveis ao ocorrer transição de status (`up.mp3` e `down.mp3` por padrão).
  - Resolução dinâmica de caminhos (`resolve_sound_path`), funcionando tanto como script quanto compilado (`.exe`).
  - Fallback acústico com `winsound` caso o arquivo de áudio não esteja disponível.
  - **Validação de Duração**: O sistema valida e aceita apenas arquivos de áudio de no **máximo 3 segundos**.
  - **Botão Mute/Unmute no Cabeçalho**: Ative ou silencie os alertas sonoros diretamente no topo da janela com o botão `🔊` / `🔇`.
  - Configuração visual com botão de teste (preview) e seleção de arquivo no painel `⚙`.
- **Checagem Ativa de Origem na Queda e na Volta**:
  - Quando um evento de queda (**DOWN**) ou recuperação (**UP**) é detectado, o sistema executa uma verificação imediata de IP e Operadora para registrar e exibir no badge a rota real no exato momento da transição.
- **Detecção de IP Público & Operadora**: Mostra seu endereço de IP de origem e provedor/ISP em um badge no topo do painel. Atualizado automaticamente a cada **5 minutos** ou forçado com **duplo clique**.
- **Transparência / Opacidade Ajustável**: Controle o nível de transparência da janela (de 20% a 100%) em tempo real.
- **Gráfico de Vida (Sparkline) com Tooltip**:
  - Pontos sutis e elegantes que desenham o histórico de latência contínuo.
  - Ao passar o mouse por cima de qualquer ponto, exibe um hint em tempo real com **hora, minuto e segundo (`HH:MM:SS`)**, status e latência em ms.
  - Linha tracejada vermelha no rodapé indicando perdas de pacotes ou quedas.
- **Logs Orientados a Eventos (Status Inicial e Mudança de Estado)**:
  - Não grava medições repetitivas a cada ciclo de polling, evitando escrita desnecessária em disco e poluição.
  - Grava **apenas o status inicial** na primeira verificação e sempre que houver **mudança de estado** (`UP` $\rightarrow$ `DOWN` ou `DOWN` $\rightarrow$ `UP`).
  - Formato compacto delimitado por `|` com retenção estrita dos **últimos 30 minutos**.
- **Indicador LED Dinâmico**: LED luminoso em verde esmeralda (serviço OK) ou vermelho (serviço alarmado/fora do ar).
- **Tipos de Monitoramento Suportados**:
  - **PING (ICMP)**: Medição contínua de latência e perda.
  - **TCP (Portas)**: Conexões diretas de socket (SSH 22, Telnet 23, MySQL 3306, PostgreSQL 5432, Redis 6379, etc.).
  - **HTTP / HTTPS**: Status code e tempo de resposta de URLs e APIs.
- **Gerenciamento em Tempo Real**:
  - Reordene seus serviços com as setas `▲` e `▼`.
  - Edite qualquer serviço com **duplo clique direto no card** ou através da tela de configurações (`⚙`).
  - Salva automaticamente tamanho da janela, posição, sons e configurações no arquivo `amonitorar.txt`.

---

## 🚀 Como Executar

### Pré-requisitos
- **Windows 10 ou 11**
- **Python 3.10+** instalado e adicionado ao `PATH` do sistema

### 1. Clonar o repositório
```bash
git clone https://github.com/seu-usuario/jacu-ia-monitor.git
cd jacu-ia-monitor
```

### 2. Instalar dependências
```bash
pip install PyQt6
```

### 3. Rodar o aplicativo
```bash
python jacu_ia_monitor.py
```

> **Dica**: Certifique-se de que os arquivos `up.mp3` e `down.mp3` (com duração de até 3 segundos cada) estejam na pasta do executável para ouvir os alertas sonoros.

---

## 📁 Estrutura de Logs Otimizada (`logs/`)

Para cada serviço cadastrado, um arquivo de log individual é mantido no diretório `logs/<id_servico>.log`.

### 📌 Política de Registro por Mudança de Status
Para maximizar a precisão e economizar disco:
1. **Status Inicial**: Gravado na primeira medição logo após o aplicativo iniciar ou após editar um serviço.
2. **Mudança de Estado**: Só haverá nova gravação quando o serviço **cair** (`UP` $\rightarrow$ `DOWN`) ou **restabelecer** (`DOWN` $\rightarrow$ `UP`).
3. **Checagem de Queda e Restauração Ativa**: No evento de transição, o aplicativo dispara uma verificação ativa de rede para capturar o IP de saída e a operadora vigentes naquele segundo exato e atualiza o badge na interface.

### 📌 Especificação dos Campos (Formato Delimitado por `|`)

$$\text{TIMESTAMP} \mid \text{IP\_ORIGEM} \mid \text{OPERADORA} \mid \text{ALVO\_MONITORADO} \mid \text{STATUS} \mid \text{LATENCIA\_MS}$$

| Posição | Campo | Descrição | Exemplo |
| :--- | :--- | :--- | :--- |
| **1** | `TIMESTAMP` | Data e hora exata da transição (`YYYY-MM-DD HH:MM:SS`) | `2026-11-11 08:52:10` |
| **2** | `IP_ORIGEM` | Endereço IP público apurado no instante do evento | `177.136.24.12` |
| **3** | `OPERADORA` | Nome do provedor/ISP da rota no momento da transição | `Claro Brasil` |
| **4** | `ALVO` | Nome e endereço/URL do alvo monitorado | `Cloudflare DNS (1.1.1.1)` |
| **5** | `STATUS` | Estado do serviço (`UP` ou `DOWN`) | `DOWN` |
| **6** | `LATENCIA` | Latência da medição em milissegundos | `0.0` |

---

## ⚙️ Arquivo de Configuração (`amonitorar.txt`)

O arquivo `amonitorar.txt` é gerado automaticamente na raiz do projeto em formato JSON:

```json
{
    "opacity": 92,
    "sound_enabled": true,
    "up_sound": "up.mp3",
    "down_sound": "down.mp3",
    "window": {
        "x": 100,
        "y": 100,
        "width": 350,
        "height": 500
    },
    "monitors": [
        {
            "id": "srv-1",
            "name": "Cloudflare DNS",
            "type": "PING",
            "target": "1.1.1.1",
            "port": 0,
            "interval": 5
        },
        {
            "id": "srv-2",
            "name": "SSH Gateway",
            "type": "TCP",
            "target": "meuhost.com.br",
            "port": 22,
            "interval": 10
        }
    ]
}
```

---

## 🖱️ Atalhos e Interações

| Ação | Como Executar |
| :--- | :--- |
| **Mover a Janela** | Clique e arraste pelo topo da barra de título |
| **Mutar / Desmutar Áudio** | Clique no botão `🔊` / `🔇` no cabeçalho |
| **Atualizar IP/ISP** | Duplo clique no badge com o globo `🌐` |
| **Ver Latência e Hora** | Passe o mouse sobre os pontos do gráfico de vida |
| **Editar Serviço** | Duplo clique sobre o card ou acesse a engrenagem `⚙` |
| **Reordenar Alvos** | Acesse `⚙` e use os botões `▲` e `▼` |
| **Escolher Sons MP3** | Acesse `⚙` e use o seletor com validação de até 3s e botão de preview |
| **Ajustar Transparência**| Acesse `⚙` e deslize a barra de opacidade (20% a 100%) |
| **Redimensionar** | Arraste o canto inferior direito (alça de redimensionamento) |
| **Fixar no Topo** | Clique no botão `📌` (Always on Top) |
| **Fechar o Programa** | Clique no botão `✕` (salva posições e encerra threads) |

---

## 📦 Gerando um Executável Standalone (`.exe`)

```bash
pip install pyinstaller
python -m PyInstaller --noconsole --onefile --name "jacu_ia_monitor" jacu_ia_monitor.py
```

O executável compilado estará disponível no caminho:
```text
dist/jacu_ia_monitor.exe
```