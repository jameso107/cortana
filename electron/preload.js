'use strict'
// Context bridge — expose only what the UI needs from Node
const { contextBridge } = require('electron')
contextBridge.exposeInMainWorld('electron', { platform: process.platform })
