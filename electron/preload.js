'use strict'
// Context bridge — expose only what the UI needs from Node.
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('cortana', {
  platform: process.platform,
  hideOverlay: () => ipcRenderer.send('overlay:hide'),
  openConsole: () => ipcRenderer.send('console:open'),
})
// Back-compat
contextBridge.exposeInMainWorld('electron', { platform: process.platform })
