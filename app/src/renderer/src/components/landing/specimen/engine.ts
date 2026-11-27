/*
 * Specimen engine: one WebGL2 canvas shared by the landing hero and the sign-in
 * panel. The canvas is created once and moved between pages, so navigating keeps
 * the scene running instead of rebuilding a context.
 *
 * Scene: a real whole-slide scan on a glass slide. The tissue is tiled, a scan
 * scores each tile (cellularity measured from the scan itself), and the top tiles
 * lift out as real high-magnification patches into a gallery linked back to their
 * sockets. Per-frame work is a handful of uniforms; motion runs in the shaders.
 */
import slideUrl from '../../../../public/images/landing/specimen-slide.webp'
import patchesUrl from '../../../../public/images/landing/specimen-patches.webp'
import {
  GLASS_FS, GLASS_VS, GLOW_FS, LINK_FS, LINK_VS, PATCH_FS, PATCH_VS, PLANE_VS, TISSUE_FS,
} from './shaders'
import { SPECIMEN_TILES } from './specimenTiles'

const CYCLE_SECONDS = 6.5
const PATCHES = SPECIMEN_TILES.picked.length
// World layout (units ~ 25 mm): a 3 x 1.1 glass slide, tissue left of centre, label on the right.
const GLASS_MIN: Vec3 = [-1.5, -0.035, -0.55]
const GLASS_SIZE: Vec3 = [3.0, 0.035, 1.1]
const SLIDE_EXTENT: [number, number] = [SPECIMEN_TILES.extent[0], SPECIMEN_TILES.extent[1]]
const SLIDE_ORIGIN: [number, number] = [-1.08, -SLIDE_EXTENT[1] / 2]
const COLS = SPECIMEN_TILES.cols
const ROWS = SPECIMEN_TILES.rows
const TILE = SLIDE_EXTENT[0] / COLS
const GRID_ORIGIN: [number, number] = [SLIDE_ORIGIN[0], SLIDE_ORIGIN[1] + (SLIDE_EXTENT[1] - ROWS * TILE) / 2]
const LABEL_RECT = [0.92, -0.5, 1.44, 0.5]
const COVER_RECT = [-1.3, -0.53, 0.5, 0.53]

type Vec3 = [number, number, number]
const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const norm = (a: Vec3): Vec3 => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l] }

function perspective(fovy: number, aspect: number, near: number, far: number) {
  const f = 1 / Math.tan(fovy / 2)
  return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, (2 * far * near) / (near - far), 0])
}
function lookAt(eye: Vec3, target: Vec3) {
  const z = norm(sub(eye, target))
  const x = norm(cross([0, 1, 0], z))
  const y = cross(z, x)
  return { matrix: new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]), x, y, z }
}
function multiply(a: Float32Array, b: Float32Array) {
  const out = new Float32Array(16)
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
    let s = 0
    for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]
    out[c * 4 + r] = s
  }
  return out
}

/** Unit quaternion (x, y, z, w; w >= 0) for the rotation whose matrix columns are a, b, c. */
function quaternionFromBasis(a: Vec3, b: Vec3, c: Vec3): [number, number, number, number] {
  const [m00, m10, m20] = a
  const [m01, m11, m21] = b
  const [m02, m12, m22] = c
  const trace = m00 + m11 + m22
  let q: [number, number, number, number]
  if (trace > 0) {
    const s = Math.sqrt(trace + 1) * 2
    q = [(m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, s / 4]
  } else if (m00 > m11 && m00 > m22) {
    const s = Math.sqrt(1 + m00 - m11 - m22) * 2
    q = [s / 4, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s]
  } else if (m11 > m22) {
    const s = Math.sqrt(1 + m11 - m00 - m22) * 2
    q = [(m01 + m10) / s, s / 4, (m12 + m21) / s, (m02 - m20) / s]
  } else {
    const s = Math.sqrt(1 + m22 - m00 - m11) * 2
    q = [(m02 + m20) / s, (m12 + m21) / s, s / 4, (m10 - m01) / s]
  }
  const l = Math.hypot(...q) || 1
  const sign = q[3] < 0 ? -1 : 1
  return [q[0] / l * sign, q[1] / l * sign, q[2] / l * sign, q[3] / l * sign]
}

function compile(gl: WebGL2RenderingContext, vs: string, fs: string) {
  const program = gl.createProgram()!
  for (const [type, source] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]] as const) {
    const shader = gl.createShader(type)!
    gl.shaderSource(shader, source)
    gl.compileShader(shader)
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || 'shader')
    gl.attachShader(program, shader)
  }
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) || 'link')
  const uniforms = new Map<string, WebGLUniformLocation | null>()
  const u = (name: string) => {
    if (!uniforms.has(name)) uniforms.set(name, gl.getUniformLocation(program, name))
    return uniforms.get(name)!
  }
  return { program, u }
}
type Program = ReturnType<typeof compile>

/** Centred unit cube, 36 vertices of position + normal. */
function cube() {
  const faces: Array<[Vec3, Vec3, Vec3]> = [
    [[0, 1, 0], [1, 0, 0], [0, 0, 1]], [[0, -1, 0], [1, 0, 0], [0, 0, -1]],
    [[1, 0, 0], [0, 0, -1], [0, 1, 0]], [[-1, 0, 0], [0, 0, 1], [0, 1, 0]],
    [[0, 0, 1], [1, 0, 0], [0, 1, 0]], [[0, 0, -1], [-1, 0, 0], [0, 1, 0]],
  ]
  const data: number[] = []
  for (const [n, u, v] of faces) {
    const corner = (a: number, b: number) => [n[0] * 0.5 + u[0] * a + v[0] * b, n[1] * 0.5 + u[1] * a + v[1] * b, n[2] * 0.5 + u[2] * a + v[2] * b, ...n]
    for (const [a, b] of [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]) data.push(...corner(a, b))
  }
  return new Float32Array(data)
}

function loadImage(url: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image()
    image.decoding = 'async'
    image.onload = () => resolve(image)
    image.onerror = reject
    image.src = url
  })
}

/** A printed slide label: frosted stock, a 2D barcode and a short accession line. */
function labelCanvas() {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 512
  const ctx = canvas.getContext('2d')
  if (!ctx) return canvas
  ctx.fillStyle = '#f7f7f9'
  ctx.fillRect(0, 0, 256, 512)
  ctx.strokeStyle = '#c7c7cc'
  ctx.lineWidth = 6
  ctx.strokeRect(3, 3, 250, 506)
  for (let i = 0; i < 2600; i++) {
    ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.035})`
    ctx.fillRect(Math.random() * 256, Math.random() * 512, 1.5, 1.5)
  }
  let seed = 11
  const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 }
  const cell = 9
  const x0 = 56
  const y0 = 300
  ctx.fillStyle = '#1d1d1f'
  for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) {
    const edge = x === 0 || y === 15 || (y === 0 && x % 2 === 0) || (x === 15 && y % 2 === 1)
    if (edge || rand() > 0.5) ctx.fillRect(x0 + x * cell, y0 + y * cell, cell, cell)
  }
  ctx.save()
  ctx.translate(128, 150)
  ctx.rotate(Math.PI / 2)
  ctx.fillStyle = '#1d1d1f'
  ctx.font = '600 34px -apple-system, "SF Pro Text", Inter, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText('PathLab', 0, -8)
  ctx.font = '400 24px "SF Mono", Menlo, monospace'
  ctx.fillStyle = '#48484f'
  ctx.fillText('S-24 0137 A1', 0, 30)
  ctx.restore()
  return canvas
}

export class SpecimenEngine {
  readonly canvas: HTMLCanvasElement
  private gl: WebGL2RenderingContext
  private programs: Record<'glass' | 'tissue' | 'patch' | 'link' | 'glow', Program>
  private quadVao: WebGLVertexArrayObject
  private cubeVao: WebGLVertexArrayObject | null = null
  private linkVao: WebGLVertexArrayObject | null = null
  private textures: { slide?: WebGLTexture; patches?: WebGLTexture; tiles?: WebGLTexture; label?: WebGLTexture } = {}
  private valid = new Uint8Array(COLS * ROWS)
  private loaded = false
  private fade = 0

  private host: HTMLElement | null = null
  private resizeObserver: ResizeObserver
  private frame = 0
  private last = 0
  private time = 0
  private running = false
  private paused = false
  private inView = true
  private pageVisible = typeof document === 'undefined' || document.visibilityState !== 'hidden'
  private staticMode = false
  private options = { shiftX: 0, shiftY: 0, distance: 3.4 }
  private pointer = { x: 0, y: 0, tx: 0, ty: 0 }
  private drag = { active: false, startX: 0, base: 0, offset: 0 }
  private hover: [number, number] = [-10, -10]
  private progressListeners = new Set<(u: number) => void>()
  private camera = { eye: [0, 0, 0] as Vec3, x: [1, 0, 0] as Vec3, y: [0, 1, 0] as Vec3, z: [0, 0, 1] as Vec3, fov: 0.6, aspect: 1 }

  constructor(canvas: HTMLCanvasElement, gl: WebGL2RenderingContext) {
    this.canvas = canvas
    this.gl = gl
    this.programs = {
      glass: compile(gl, GLASS_VS, GLASS_FS),
      tissue: compile(gl, PLANE_VS, TISSUE_FS),
      patch: compile(gl, PATCH_VS, PATCH_FS),
      link: compile(gl, LINK_VS, LINK_FS),
      glow: compile(gl, PLANE_VS, GLOW_FS),
    }
    this.quadVao = gl.createVertexArray()!
    gl.bindVertexArray(this.quadVao)
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer())
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW)
    gl.enableVertexAttribArray(0)
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0)
    gl.bindVertexArray(null)
    this.textures.label = this.texture(labelCanvas(), true)
    void this.load()

    this.resizeObserver = new ResizeObserver(() => this.resize())
    canvas.addEventListener('pointermove', this.onPointerMove)
    canvas.addEventListener('pointerleave', this.onPointerLeave)
    canvas.addEventListener('pointerdown', this.onPointerDown)
    window.addEventListener('pointerup', this.onPointerUp)
    document.addEventListener('visibilitychange', this.onVisibility)
  }

  private texture(source: TexImageSource, mipmaps: boolean) {
    const gl = this.gl
    const texture = gl.createTexture()!
    gl.bindTexture(gl.TEXTURE_2D, texture)
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source)
    if (mipmaps) gl.generateMipmap(gl.TEXTURE_2D)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mipmaps ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    const aniso = gl.getExtension('EXT_texture_filter_anisotropic')
    if (aniso && mipmaps) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(8, gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT)))
    return texture
  }

  private async load() {
    const [slide, patches] = await Promise.all([loadImage(slideUrl), loadImage(patchesUrl)]).catch(() => [null, null])
    if (!slide || !patches) return
    const gl = this.gl
    this.textures.slide = this.texture(slide, true)
    this.textures.patches = this.texture(patches, true)

    // Scores and picks are baked by scripts/build-landing-assets.py from the full-resolution scan,
    // so each extracted patch in the atlas is exactly the tile it leaves behind.
    const tiles: Array<{ col: number; row: number; score: number }> = []
    SPECIMEN_TILES.scores.forEach((score, i) => {
      if (score <= 0) return
      const col = i % COLS
      const row = Math.floor(i / COLS)
      this.valid[i] = 1
      tiles.push({ col, row, score })
    })
    const picked = SPECIMEN_TILES.picked.map(([col, row]) => ({ col, row }))
    const data = new Uint8Array(COLS * ROWS * 4)
    tiles.forEach(tile => {
      const i = (tile.row * COLS + tile.col) * 4
      data[i] = Math.round(tile.score * 255)
      data[i + 1] = 255
      data[i + 2] = 255
      data[i + 3] = 255
    })
    picked.forEach((tile, rank) => { data[(tile.row * COLS + tile.col) * 4 + 1] = rank })
    const tilesTexture = gl.createTexture()!
    gl.bindTexture(gl.TEXTURE_2D, tilesTexture)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, COLS, ROWS, 0, gl.RGBA, gl.UNSIGNED_BYTE, data)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST)
    this.textures.tiles = tilesTexture

    const instance = new Float32Array(picked.flatMap((tile, rank) => [tile.col, tile.row, rank]))
    const instanceBuffer = gl.createBuffer()!
    gl.bindBuffer(gl.ARRAY_BUFFER, instanceBuffer)
    gl.bufferData(gl.ARRAY_BUFFER, instance, gl.STATIC_DRAW)

    this.cubeVao = gl.createVertexArray()!
    gl.bindVertexArray(this.cubeVao)
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer())
    gl.bufferData(gl.ARRAY_BUFFER, cube(), gl.STATIC_DRAW)
    gl.enableVertexAttribArray(0)
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 24, 0)
    gl.enableVertexAttribArray(1)
    gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 24, 12)
    gl.bindBuffer(gl.ARRAY_BUFFER, instanceBuffer)
    gl.enableVertexAttribArray(2)
    gl.vertexAttribPointer(2, 3, gl.FLOAT, false, 12, 0)
    gl.vertexAttribDivisor(2, 1)

    this.linkVao = gl.createVertexArray()!
    gl.bindVertexArray(this.linkVao)
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer())
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 1]), gl.STATIC_DRAW)
    gl.enableVertexAttribArray(0)
    gl.vertexAttribPointer(0, 1, gl.FLOAT, false, 4, 0)
    gl.bindBuffer(gl.ARRAY_BUFFER, instanceBuffer)
    gl.enableVertexAttribArray(2)
    gl.vertexAttribPointer(2, 3, gl.FLOAT, false, 12, 0)
    gl.vertexAttribDivisor(2, 1)
    gl.bindVertexArray(null)

    this.loaded = true
    this.requestRender()
  }

  /** Move the canvas into a page's stage. Only one stage holds it at a time. */
  attach(host: HTMLElement) {
    if (this.host && this.host !== host) this.resizeObserver.unobserve(this.host)
    this.host = host
    host.appendChild(this.canvas)
    this.resizeObserver.observe(host)
    this.resize()
    this.start()
  }

  detach(host: HTMLElement) {
    if (this.host !== host) return
    this.resizeObserver.unobserve(host)
    this.host = null
    this.stop()
  }

  isPaused() { return this.paused }
  /** Cycle position in [0, 1) on every rendered frame. */
  onProgress(listener: (u: number) => void) { this.progressListeners.add(listener); return () => { this.progressListeners.delete(listener) } }
  setPaused(paused: boolean) { this.paused = paused; paused ? this.stop() : this.start() }
  setInView(inView: boolean) { this.inView = inView; inView ? this.start() : this.stop() }
  setStatic(value: boolean) {
    this.staticMode = value
    if (value) { this.time = CYCLE_SECONDS * 0.6; this.fade = 1; this.stop(); this.requestRender() } else this.start()
  }

  private resize() {
    if (!this.host) return
    const style = getComputedStyle(this.host)
    const read = (name: string, fallback: number) => { const value = parseFloat(style.getPropertyValue(name)); return Number.isFinite(value) ? value : fallback }
    this.options = { shiftX: read('--stage-shift-x', 0), shiftY: read('--stage-shift-y', 0), distance: read('--stage-distance', 3.4) }
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const width = Math.max(1, Math.round(this.host.clientWidth * dpr))
    const height = Math.max(1, Math.round(this.host.clientHeight * dpr))
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width
      this.canvas.height = height
    }
    this.requestRender()
  }

  private start() {
    if (this.running || this.paused || !this.inView || !this.pageVisible || this.staticMode || !this.host) return
    this.running = true
    this.last = performance.now()
    this.frame = requestAnimationFrame(this.tick)
  }

  private stop() {
    this.running = false
    if (this.frame) cancelAnimationFrame(this.frame)
    this.frame = 0
  }

  private requestRender() {
    if (this.running || !this.host) return
    requestAnimationFrame(() => this.render())
  }

  private tick = (now: number) => {
    if (!this.running) return
    const dt = Math.min(0.05, (now - this.last) / 1000)
    this.last = now
    if (this.loaded) {
      this.time += dt
      this.fade = Math.min(1, this.fade + dt * 1.5)
    }
    this.render()
    this.frame = requestAnimationFrame(this.tick)
  }

  private render() {
    const gl = this.gl
    const { width, height } = this.canvas
    if (!this.host || width < 2 || height < 2) return
    const t = this.time
    const u = (t / CYCLE_SECONDS) % 1
    const animate = this.staticMode ? 0 : 1

    this.pointer.x += (this.pointer.tx - this.pointer.x) * 0.08
    this.pointer.y += (this.pointer.ty - this.pointer.y) * 0.08
    if (!this.drag.active) this.drag.offset *= 0.97
    const aspect = width / height
    this.camera.aspect = aspect
    const azimuth = -0.5 + Math.sin(t * 0.25) * 0.08 * animate + this.pointer.x * 0.1 + this.drag.offset
    const elevation = 0.68 - this.pointer.y * 0.06
    const distance = this.options.distance * Math.max(1, 1.5 / aspect)
    const target: Vec3 = [-0.15, 0.22, 0]
    const eye: Vec3 = [
      target[0] + distance * Math.cos(elevation) * Math.sin(azimuth),
      target[1] + distance * Math.sin(elevation),
      target[2] + distance * Math.cos(elevation) * Math.cos(azimuth),
    ]
    const view = lookAt(eye, target)
    Object.assign(this.camera, { eye, x: view.x, y: view.y, z: view.z })
    const viewProj = multiply(perspective(this.camera.fov, aspect, 0.1, 30), view.matrix)
    const shift: [number, number] = [this.options.shiftX, this.options.shiftY]
    // Patch orientation in the gallery: local x -> camera right, y (face normal) -> toward camera, z -> camera down.
    const rotation = quaternionFromBasis(view.x, view.z, [-view.y[0], -view.y[1], -view.y[2]])
    this.progressListeners.forEach(listener => listener(u))
    // Gallery hovers above the far half of the slide, facing the camera.
    const gallery: Vec3 = [target[0] - view.z[0] * 0.3, 0.6, target[2] - view.z[2] * 0.3]

    gl.bindFramebuffer(gl.FRAMEBUFFER, null)
    gl.viewport(0, 0, width, height)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT)
    gl.enable(gl.DEPTH_TEST)
    gl.depthFunc(gl.LEQUAL)
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA)

    const common = (program: Program) => {
      gl.useProgram(program.program)
      gl.uniformMatrix4fv(program.u('uViewProj'), false, viewProj)
      gl.uniform2f(program.u('uShift'), shift[0], shift[1])
      gl.uniform1f(program.u('uU'), u)
      gl.uniform1f(program.u('uTime'), t)
      gl.uniform2f(program.u('uGridOrigin'), GRID_ORIGIN[0], GRID_ORIGIN[1])
      gl.uniform1f(program.u('uTile'), TILE)
      gl.uniform3f(program.u('uGallery'), gallery[0], gallery[1], gallery[2])
      gl.uniform3f(program.u('uRight'), view.x[0], view.x[1], view.x[2])
      gl.uniform3f(program.u('uUp'), view.y[0], view.y[1], view.y[2])
      gl.uniform4f(program.u('uRot'), rotation[0], rotation[1], rotation[2], rotation[3])
    }
    const plane = (program: Program, origin: [number, number], extent: [number, number], y: number) => {
      common(program)
      gl.uniform2f(program.u('uOrigin'), origin[0], origin[1])
      gl.uniform2f(program.u('uExtent'), extent[0], extent[1])
      gl.uniform1f(program.u('uY'), y)
    }

    // Light pooled beneath the slide.
    gl.depthMask(false)
    gl.bindVertexArray(this.quadVao)
    plane(this.programs.glow, [-4.5, -2.5], [9, 5], -0.12)
    gl.drawArrays(gl.TRIANGLES, 0, 6)

    // Patches (opaque) first so the glass and tissue blend over correctly.
    const ready = this.loaded && this.textures.slide && this.textures.patches && this.textures.tiles
    if (ready && this.cubeVao && this.linkVao) {
      gl.depthMask(true)
      gl.disable(gl.BLEND)
      const patch = this.programs.patch
      common(patch)
      gl.uniform2f(patch.u('uSlideOrigin'), SLIDE_ORIGIN[0], SLIDE_ORIGIN[1])
      gl.uniform2f(patch.u('uSlideExtent'), SLIDE_EXTENT[0], SLIDE_EXTENT[1])
      gl.activeTexture(gl.TEXTURE0)
      gl.bindTexture(gl.TEXTURE_2D, this.textures.slide!)
      gl.uniform1i(patch.u('uSlide'), 0)
      gl.activeTexture(gl.TEXTURE1)
      gl.bindTexture(gl.TEXTURE_2D, this.textures.patches!)
      gl.uniform1i(patch.u('uPatches'), 1)
      gl.bindVertexArray(this.cubeVao)
      gl.drawArraysInstanced(gl.TRIANGLES, 0, 36, PATCHES)
      gl.enable(gl.BLEND)
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
    }

    gl.depthMask(false)
    if (ready) {
      const tissue = this.programs.tissue
      plane(tissue, SLIDE_ORIGIN, SLIDE_EXTENT, 0.0006)
      gl.uniform2f(tissue.u('uGrid'), COLS, ROWS)
      gl.uniform2f(tissue.u('uHover'), this.hover[0], this.hover[1])
      gl.activeTexture(gl.TEXTURE0)
      gl.bindTexture(gl.TEXTURE_2D, this.textures.slide!)
      gl.uniform1i(tissue.u('uSlide'), 0)
      gl.activeTexture(gl.TEXTURE2)
      gl.bindTexture(gl.TEXTURE_2D, this.textures.tiles!)
      gl.uniform1i(tissue.u('uTiles'), 2)
      gl.bindVertexArray(this.quadVao)
      gl.drawArrays(gl.TRIANGLES, 0, 6)
    }

    // Glass: a box drawn back faces first, then front faces.
    if (this.cubeVao) {
      const glass = this.programs.glass
      common(glass)
      gl.uniform3f(glass.u('uMin'), GLASS_MIN[0], GLASS_MIN[1], GLASS_MIN[2])
      gl.uniform3f(glass.u('uSize'), GLASS_SIZE[0], GLASS_SIZE[1], GLASS_SIZE[2])
      gl.uniform3f(glass.u('uEye'), eye[0], eye[1], eye[2])
      gl.uniform4f(glass.u('uLabelRect'), LABEL_RECT[0], LABEL_RECT[1], LABEL_RECT[2], LABEL_RECT[3])
      gl.uniform4f(glass.u('uCoverRect'), COVER_RECT[0], COVER_RECT[1], COVER_RECT[2], COVER_RECT[3])
      gl.activeTexture(gl.TEXTURE3)
      gl.bindTexture(gl.TEXTURE_2D, this.textures.label!)
      gl.uniform1i(glass.u('uLabel'), 3)
      gl.bindVertexArray(this.cubeVao)
      gl.enable(gl.CULL_FACE)
      gl.cullFace(gl.FRONT)
      gl.drawArrays(gl.TRIANGLES, 0, 36)
      gl.cullFace(gl.BACK)
      gl.drawArrays(gl.TRIANGLES, 0, 36)
      gl.disable(gl.CULL_FACE)
    }

    if (ready && this.linkVao) {
      common(this.programs.link)
      gl.bindVertexArray(this.linkVao)
      gl.drawArraysInstanced(gl.LINES, 0, 2, PATCHES)
    }
    gl.depthMask(true)
    gl.bindVertexArray(null)
    this.canvas.style.opacity = String(this.fade)
  }

  /** Ray from the camera through the pointer, intersected with the slide plane. */
  private pick(clientX: number, clientY: number) {
    const bounds = this.canvas.getBoundingClientRect()
    const ndcX = ((clientX - bounds.left) / bounds.width) * 2 - 1 - this.options.shiftX
    const ndcY = 1 - ((clientY - bounds.top) / bounds.height) * 2 - this.options.shiftY
    const tan = Math.tan(this.camera.fov / 2)
    const { eye, x, y, z } = this.camera
    const dir = norm([0, 1, 2].map(i => -z[i] + x[i] * ndcX * tan * this.camera.aspect + y[i] * ndcY * tan) as Vec3)
    if (dir[1] >= -1e-4) return null
    const d = -eye[1] / dir[1]
    const col = Math.floor((eye[0] + dir[0] * d - GRID_ORIGIN[0]) / TILE)
    const row = Math.floor((eye[2] + dir[2] * d - GRID_ORIGIN[1]) / TILE)
    if (col < 0 || row < 0 || col >= COLS || row >= ROWS || !this.valid[row * COLS + col]) return null
    return [col, row] as [number, number]
  }

  private onPointerMove = (event: PointerEvent) => {
    const bounds = this.canvas.getBoundingClientRect()
    this.pointer.tx = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
    this.pointer.ty = ((event.clientY - bounds.top) / bounds.height) * 2 - 1
    if (this.drag.active) this.drag.offset = this.drag.base + ((event.clientX - this.drag.startX) / bounds.width) * 2.4
    const hit = event.pointerType === 'mouse' && !this.drag.active ? this.pick(event.clientX, event.clientY) : null
    this.hover = hit ?? [-10, -10]
    this.canvas.style.cursor = this.drag.active ? 'grabbing' : hit ? 'pointer' : 'grab'
    this.requestRender()
  }

  private onPointerLeave = () => {
    this.pointer.tx = 0
    this.pointer.ty = 0
    this.hover = [-10, -10]
    this.requestRender()
  }

  private onPointerDown = (event: PointerEvent) => {
    if (event.pointerType !== 'mouse' || event.button !== 0) return
    this.drag = { active: true, startX: event.clientX, base: this.drag.offset, offset: this.drag.offset }
    this.canvas.style.cursor = 'grabbing'
  }

  private onPointerUp = () => {
    if (!this.drag.active) return
    this.drag.active = false
    this.canvas.style.cursor = 'grab'
  }

  private onVisibility = () => {
    this.pageVisible = document.visibilityState !== 'hidden'
    this.pageVisible ? this.start() : this.stop()
  }
}

let engine: SpecimenEngine | null | undefined

/** The shared engine, or null where WebGL2 is unavailable (the stage then shows its backdrop only). */
export function getSpecimenEngine(): SpecimenEngine | null {
  if (engine !== undefined) return engine
  try {
    const canvas = document.createElement('canvas')
    canvas.className = 'specimen-stage__canvas'
    const gl = canvas.getContext('webgl2', { antialias: true, alpha: true, premultipliedAlpha: true, powerPreference: 'high-performance' })
    engine = gl ? new SpecimenEngine(canvas, gl) : null
    if (import.meta.env.DEV) (window as unknown as { __specimen?: SpecimenEngine | null }).__specimen = engine
  } catch {
    engine = null
  }
  return engine
}
