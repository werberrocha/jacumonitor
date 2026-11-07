# ⚡ jacu.ia monitor (beta 0.1)

Um aplicativo moderno no estilo **Gadget / HUD Flutuante** para **Windows 11** desenvolvido em Python e PyQt6. Projetado para ficar sobreposto na sua área de trabalho de forma elegante e discreta, monitorando em tempo real a integridade de servidores, sites, APIs e serviços de infraestrutura.

---

## ✨ Principais Funcionalidades

- **Janela HUD Sempre no Topo (Always-on-Top)**: Fixe o gadget com o botão `📌` para que ele continue visível mesmo com outros programas abertos.
- **Transparência / Opacidade Ajustável**: Controle o nível de transparência da janela (de 20% a 100%) em tempo real.
- **Gráfico de Vida (Sparkline)**: Linha de batimento cardíaco com histórico de latência (ms) e indicação imediata de quedas/perda de pacotes em vermelho tracejado.
- **Indicador LED Dinâmico**: LED luminoso em verde esmeralda (serviço OK) ou vermelho pulsante (serviço alarmado/fora do ar).
- **Tipos de Monitoramento Suportados**:
  - `PING`: Testes de ICMP com medição de latência em milissegundos.
  - `TCP`: Testes de porta de rede (SSH, MySQL, PostgreSQL, Telnet, Redis, portas customizadas).
  - `HTTP / HTTPS`: Verificação de disponibilidade e tempo de resposta de sites e endpoints de APIs.
- **Duplo Clique para Edição Rápida**: Dê um duplo clique direto em qualquer card para editar suas configurações.
- **Reordenação de Visualização**: Suba (▲) ou desça (▼) a prioridade de visualização dos servidores pelo painel de configurações.
- **Redimensionável com Memória de Tela**: Salva tamanho e coordenadas `(x, y)` ao fechar e detecta múltiplos monitores no Windows para nunca abrir fora da tela visível.
- **Persistência em JSON**: Todos os servidores, ordenação, opacidade e posições são salvos no arquivo local `amonitorar.txt`.

---

## 📋 Pré-requisitos

- **Sistema Operacional**: Windows 10 ou Windows 11 (recomendado).
- **Python**: Versão 3.10 ou superior instalada.

---

## 🚀 Instalação e Execução

### 1. Clonar o repositório
```bash
git clone https://github.com/seu-usuario/jacu-monitor.git
cd jacu-monitor
```

### 2. (Opcional, mas recomendado) Criar um ambiente virtual
```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Instalar dependências
```bash
pip install PyQt6
```

### 4. Executar o aplicativo
```bash
python jacu_monitor.py
```

> **Dica**: Para rodar o programa sem abrir a janela preta do console do Windows, altere a extensão para `.pyw` ou execute:
> ```bash
> pythonw jacu_monitor.py
> ```

---

## ⚙️ Estrutura do Arquivo `amonitorar.txt`

O arquivo `amonitorar.txt` é gerado automaticamente na primeira execução com uma estrutura em JSON:

```json
{
    "opacity": 92,
    "window": {
        "x": 100,
        "y": 100,
        "width": 350,
        "height": 480
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
            "id": "srv-4",
            "name": "SSH Servidor",
            "type": "TCP",
            "target": "meu.servidor.com",
            "port": 22,
            "interval": 8
        },
        {
            "id": "srv-3",
            "name": "API Externa",
            "type": "HTTP",
            "target": "https://api.exemplo.com/health",
            "port": 443,
            "interval": 10
        }
    ]
}
```

---

## 🎯 Atalhos e Interações

| Ação | Como fazer |
|---|---|
| **Mover a Janela** | Clique e arraste pelo topo da barra de título |
| **Redimensionar** | Arraste o canto inferior direito (alça de redimensionamento) |
| **Fixar no Topo** | Clique no botão `📌` (Always on Top) |
| **Editar Serviço** | Duplo clique sobre o card ou acesse a engrenagem `⚙` |
| **Reordenar Alvos** | Acesse `⚙` e use as setas `▲` e `▼` |
| **Ajustar Transparência**| Acesse `⚙` e deslize a barra de opacidade |
| **Fechar a Aplicação** | Clique no botão `✕` (salva dimensões e encerra todas as threads) |

---

## 📦 Gerando um Executável `.exe` (Standalone)

Para criar um executável único para o Windows que não dependa do Python instalado:

```bash
pip install pyinstaller
python -m PyInstaller --noconsole --onefile --name "jacu_monitor" jacu_ia_monitor.py

```
O arquivo gerado ficará disponível dentro da pasta `dist/jacu_monitor.exe`.

---

## 📄 Licença

Distribuído sob a licença MIT. Consulte `LICENSE` para obter mais informações.