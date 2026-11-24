# Xed Win11Tabs Plugin (`win11tabs`)

Plugin nativo em Python (`libpeas` / `Xed.WindowActivatable`) para o **Editor de Texto do Linux Mint (`xed`)**, trazendo o comportamento moderno de múltiplas guias e persistência automática de rascunhos de sessão inspirado no **Bloco de Notas do Windows 11**.

## Funcionalidades

- **Barra de guias sempre visível:** Mantém o cabeçalho de guias (`Xed.Notebook`) visível mesmo quando apenas 1 documento está aberto, com botão **`+` (Nova guia)** integrado à barra de abas.
- **Persistência automática de rascunhos e sessão (`~/.config/xed/session_state.json`):**
  - Salva automaticamente em tempo real (debounce de `300ms`) tudo o que é digitado em abas `"Sem título"` (sem exigir criar/salvar arquivos `.txt` no computador) e alterações não salvas em arquivos abertos.
  - Preserva a ordem das guias, a guia ativa e a posição do cursor em cada documento.
- **Fechamento silencioso da janela:** Ao fechar o Editor de Texto (`✕` da janela, `Alt+F4` ou `Ctrl+Q`), o estado completo das abas é salvo na sessão local e a janela fecha instantaneamente sem exibir caixas de diálogo exigindo salvar arquivo.
- **Restauração automática ao abrir:** Ao reabrir o `xed` (pelo menu ou ao clicar em um novo arquivo `.txt`), todas as guias e rascunhos da sessão anterior são restaurados automaticamente.
- **Atalhos de teclado adicionais:**
  - `Ctrl + T`: Nova guia
  - `Ctrl + Tab` / `Ctrl + Shift + Tab`: Alternar entre guias abertas
  - `Ctrl + W`: Fechar guia atual

## Instalação

1. Copie `win11tabs.plugin` e a pasta `win11tabs/` para `~/.local/share/xed/plugins/`:
   ```bash
   mkdir -p ~/.local/share/xed/plugins
   cp -r win11tabs.plugin win11tabs ~/.local/share/xed/plugins/
   ```
2. Ative o plugin no `xed` (em **Editar -> Preferências -> Plugins** ou via terminal):
   ```bash
   gsettings set org.x.editor.plugins active-plugins "$(gsettings get org.x.editor.plugins active-plugins | sed "s/]$/, 'win11tabs']/")"
   ```
