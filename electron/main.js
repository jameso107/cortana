'use strict'

const { app, BrowserWindow, Tray, Menu, nativeImage, dialog, shell,
        globalShortcut, ipcMain, screen } = require('electron')
const { spawn, execSync }  = require('child_process')
const path  = require('path')
const fs    = require('fs')
const https = require('https')
const http  = require('http')

// ── Paths ──────────────────────────────────────────────────────────────────
const IS_PACKAGED = app.isPackaged
const ROOT        = IS_PACKAGED
  ? path.join(process.resourcesPath)           // inside .app/Contents/Resources/
  : path.join(__dirname, '..')                 // repo root (dev mode)

const REPO_ROOT   = path.join(__dirname, '..')        // ~/cortana/ in dev
const PYTHON      = IS_PACKAGED
  ? path.join(process.env.HOME, 'cortana', '.venv', 'bin', 'python')
  : path.join(REPO_ROOT, '.venv', 'bin', 'python')

// llama-server binary — expect it on PATH or in ~/.cortana/bin/
const LLAMA_SERVER = (() => {
  try { execSync('which llama-server'); return 'llama-server' } catch {}
  const home = path.join(process.env.HOME, '.cortana', 'bin', 'llama-server')
  if (fs.existsSync(home)) return home
  return null
})()

const MODEL_PATH  = path.join(process.env.HOME, '.cortana', 'models', 'Qwen3-30B-A3B-Q6_K.gguf')

// Ports
const PORT_CHAT = 8765
const PORT_TERM = 8766
const PORT_API  = 8767

// ── State ──────────────────────────────────────────────────────────────────
let mainWindow  = null
let splashWin   = null
let tray        = null
let overlayWin  = null
let procs       = []   // child processes to kill on quit

// ── Splash window ──────────────────────────────────────────────────────────
function createSplash() {
  splashWin = new BrowserWindow({
    width: 480, height: 320,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    webPreferences: { nodeIntegration: false },
  })
  splashWin.loadFile(path.join(__dirname, 'splash.html'))
  splashWin.center()
}

function setSplashStatus(msg) {
  if (!splashWin || splashWin.isDestroyed()) return
  splashWin.webContents.executeJavaScript(
    `document.getElementById('status').textContent = ${JSON.stringify(msg)}`
  ).catch(() => {})
}

// ── Console window (the full tabbed UI — opened on demand) ───────────────────
function openConsole() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show(); mainWindow.focus(); return
  }
  mainWindow = new BrowserWindow({
    width: 1400, height: 900,
    minWidth: 900, minHeight: 600,
    show: false,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#000408',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  mainWindow.loadURL(`http://127.0.0.1:${PORT_API}`)
  mainWindow.once('ready-to-show', () => { mainWindow.show(); mainWindow.focus() })
  mainWindow.on('closed', () => { mainWindow = null })
  mainWindow.on('close', (e) => {
    if (process.platform === 'darwin' && !app.isQuiting) { e.preventDefault(); mainWindow.hide() }
  })
}

// ── Summon overlay (the ambient, primary surface) ────────────────────────────
function createOverlay() {
  overlayWin = new BrowserWindow({
    width: 720, height: 540,
    frame: false, transparent: true, resizable: false, movable: true,
    alwaysOnTop: true, skipTaskbar: true, show: false,
    fullscreenable: false, hasShadow: true,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  overlayWin.loadURL(`http://127.0.0.1:${PORT_API}/#overlay`)
  overlayWin.setAlwaysOnTop(true, 'floating')
  overlayWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  // Ambient: dismiss when the user clicks away.
  overlayWin.on('blur', () => { if (!app.isQuiting) overlayWin?.hide() })
  overlayWin.on('closed', () => { overlayWin = null })
}

function showOverlay() {
  if (!overlayWin || overlayWin.isDestroyed()) createOverlay()
  const { width } = screen.getPrimaryDisplay().workAreaSize
  const b = overlayWin.getBounds()
  overlayWin.setPosition(Math.round((width - b.width) / 2), 140)
  overlayWin.show()
  overlayWin.focus()
}

function toggleOverlay() {
  if (overlayWin && overlayWin.isVisible()) overlayWin.hide()
  else showOverlay()
}

// ── Tray ───────────────────────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray.png')
  const icon = fs.existsSync(iconPath)
    ? nativeImage.createFromPath(iconPath).resize({ width: 18, height: 18 })
    : nativeImage.createEmpty()

  tray = new Tray(icon)
  tray.setToolTip('Cortana — ⌘⇧Space to summon')
  tray.on('click', () => toggleOverlay())
  updateTrayMenu('starting')
}

function updateTrayMenu(state) {
  const label = { starting: '● Starting…', ready: '● Online', error: '⚠ Error' }[state] || '● Cortana'
  const menu = Menu.buildFromTemplate([
    { label: 'Cortana', enabled: false },
    { label, enabled: false },
    { type: 'separator' },
    { label: 'Summon Cortana', accelerator: 'CmdOrCtrl+Shift+Space', click: () => showOverlay() },
    { label: 'Open Console', click: () => openConsole() },
    { label: 'Restart services', click: restartServices },
    { type: 'separator' },
    { label: 'Quit Cortana', click: () => { app.isQuiting = true; app.quit() } },
  ])
  tray?.setContextMenu(menu)
}

// ── Process management ─────────────────────────────────────────────────────
function spawnProc(cmd, args, opts = {}) {
  const proc = spawn(cmd, args, {
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    ...opts,
  })
  procs.push(proc)
  proc.stdout?.on('data', d => console.log(`[${path.basename(cmd)}]`, d.toString().trim()))
  proc.stderr?.on('data', d => console.error(`[${path.basename(cmd)}]`, d.toString().trim()))
  return proc
}

function killAll() {
  for (const p of procs) {
    try { process.kill(-p.pid, 'SIGTERM') } catch {}
    try { p.kill('SIGTERM') } catch {}
  }
  procs = []
}

function isPortOpen(port) {
  return new Promise(resolve => {
    const req = http.get(`http://127.0.0.1:${port}/`, res => { res.destroy(); resolve(true) })
    req.on('error', () => resolve(false))
    req.setTimeout(800, () => { req.destroy(); resolve(false) })
  })
}

function waitForPort(port, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs
    const attempt = () => {
      const req = http.get(`http://127.0.0.1:${port}/`, res => {
        res.destroy()
        resolve()
      })
      req.on('error', () => {
        if (Date.now() > deadline) return reject(new Error(`Port ${port} timeout`))
        setTimeout(attempt, 500)
      })
      req.setTimeout(500, () => { req.destroy(); setTimeout(attempt, 500) })
    }
    attempt()
  })
}

// ── Service startup ────────────────────────────────────────────────────────
async function startServices() {
  // 1. llama-server (skip if already running)
  const llamaAlreadyUp = await isPortOpen(8080)
  if (!llamaAlreadyUp && LLAMA_SERVER && fs.existsSync(MODEL_PATH)) {
    setSplashStatus('Starting inference engine…')
    spawnProc(LLAMA_SERVER, [
      '--model', MODEL_PATH,
      '--port', '8080',
      '--ctx-size', '16384',
      '--n-gpu-layers', '99',
      '--threads', '8',
      '--parallel', '1',
      '--host', '127.0.0.1',
    ])
    // Wait up to 60s for llama-server (model load takes a while)
    setSplashStatus('Loading model (this takes ~30s)…')
    try {
      await waitForPort(8080, 90000)
    } catch {
      console.warn('llama-server did not start in time — continuing anyway')
    }
  } else if (llamaAlreadyUp) {
    console.log('llama-server already running on :8080 — skipping spawn.')
  } else {
    console.warn('llama-server or model not found — skipping.')
  }

  // 2. Docker / SearXNG
  setSplashStatus('Starting search engine…')
  try {
    const repoRoot = IS_PACKAGED ? null : REPO_ROOT
    if (repoRoot && fs.existsSync(path.join(repoRoot, 'docker-compose.yml'))) {
      spawn('docker', ['compose', 'up', '-d'], { cwd: repoRoot, detached: true, stdio: 'ignore' })
    }
  } catch { /* docker optional */ }

  // 3. Cortana Python daemon (skip if already running)
  const daemonAlreadyUp = await isPortOpen(PORT_API)
  if (daemonAlreadyUp) {
    console.log('Cortana daemon already running — skipping spawn.')
    setSplashStatus('Cortana online.')
    return
  }
  setSplashStatus('Starting Cortana daemon…')
  // Use the supervisor script so Cortana can restart herself via SIGUSR1
  const supervisorScript = IS_PACKAGED
    ? path.join(ROOT, 'scripts', 'supervisor.sh')
    : path.join(REPO_ROOT, 'scripts', 'supervisor.sh')
  spawnProc('bash', [supervisorScript, '--voice'], {
    cwd: IS_PACKAGED ? ROOT : REPO_ROOT,
    detached: false,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  })

  // Wait for the API server to be ready
  setSplashStatus('Waiting for services…')
  await waitForPort(PORT_API, 60000)

  setSplashStatus('Cortana online.')
}

async function restartServices() {
  killAll()
  await new Promise(r => setTimeout(r, 1500))
  await startServices()
  mainWindow?.reload()
  overlayWin?.reload()
}

// Overlay control from the renderer (Esc to dismiss, "Open console" link).
ipcMain.on('overlay:hide', () => overlayWin?.hide())
ipcMain.on('console:open', () => { overlayWin?.hide(); openConsole() })

function registerHotkey() {
  // Global summon shortcut — try the primary, fall back if it's taken.
  for (const accel of ['CommandOrControl+Shift+Space', 'Alt+Space']) {
    if (globalShortcut.register(accel, toggleOverlay)) {
      console.log('Summon hotkey:', accel)
      return
    }
  }
  console.warn('Could not register a global summon hotkey.')
}

// ── App lifecycle ──────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  if (app.dock) app.dock.hide()   // menubar agent — live in the tray, not the dock
  createSplash()
  createTray()
  updateTrayMenu('starting')

  try {
    await startServices()
    updateTrayMenu('ready')
    createOverlay()
    registerHotkey()
    if (splashWin && !splashWin.isDestroyed()) splashWin.close()
    showOverlay()   // greet the user once so they see Cortana is live
  } catch (err) {
    updateTrayMenu('error')
    dialog.showErrorBox('Cortana startup failed', String(err))
  }
})

app.on('window-all-closed', () => {
  // Menubar agent — keep running even with no windows.
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => showOverlay())

app.on('will-quit', () => globalShortcut.unregisterAll())

app.on('before-quit', () => {
  app.isQuiting = true
  killAll()
  // Stop docker
  try {
    const repoRoot = IS_PACKAGED ? null : REPO_ROOT
    if (repoRoot) execSync('docker compose down', { cwd: repoRoot, timeout: 5000 })
  } catch {}
})
