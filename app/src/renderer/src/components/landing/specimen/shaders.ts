/* GLSL for the specimen stage. Imagery is a real whole-slide scan and real
   high-magnification patches (see public/images/landing/SOURCES.md). */

/* Shared 9 s timeline, u in [0, 1):
   0.00–0.10 tile grid settles on the tissue
   0.04–0.26 scan; each tile's attention fills in behind it
   0.30–0.48 the top tiles lift out and become high-magnification patches
   0.48–0.78 patches hold in a gallery, linked to where they came from
   0.78–0.92 patches return; 0.88–0.98 overlays fade */
const TIMELINE = /* glsl */ `
uniform float uU;
// Tiles are analysed along a diagonal wavefront; front() is the brief moment a tile is being processed.
float scanStart(float x) { return 0.04 + 0.22 * x; }
float scanAt(float x) { float start = scanStart(x); return smoothstep(start, start + 0.05, uU) * (1.0 - smoothstep(0.88, 0.98, uU)); }
float frontAt(float x) { float start = scanStart(x); return smoothstep(start - 0.015, start, uU) * (1.0 - smoothstep(start + 0.01, start + 0.05, uU)); }
float liftAt(float rank) {
  float d = rank * 0.009;
  return smoothstep(0.30 + d, 0.44 + d, uU) * (1.0 - smoothstep(0.78 + d * 0.5, 0.9 + d * 0.5, uU));
}
`

const INFERNO = /* glsl */ `
vec3 inferno(float t) {
  t = clamp(t, 0.0, 1.0);
  const vec3 c0 = vec3(0.0002189, 0.0016510, -0.0194809);
  const vec3 c1 = vec3(0.1065134, 0.5639564, 3.9327124);
  const vec3 c2 = vec3(11.6024931, -3.9728540, -15.9423941);
  const vec3 c3 = vec3(-41.7039961, 17.4363989, 44.3541452);
  const vec3 c4 = vec3(77.1629357, -33.4023589, -81.8073093);
  const vec3 c5 = vec3(-71.3194282, 32.6260643, 73.2095199);
  const vec3 c6 = vec3(25.1311262, -12.2426690, -23.0703250);
  return c0 + t * (c1 + t * (c2 + t * (c3 + t * (c4 + t * (c5 + t * c6)))));
}
`

const PROJECT = /* glsl */ `
uniform mat4 uViewProj;
uniform vec2 uShift;
vec4 project(vec3 p) { vec4 clip = uViewProj * vec4(p, 1.0); clip.xy += uShift * clip.w; return clip; }
`

/** Glass slab: a unit box scaled by uniforms. */
export const GLASS_VS = /* glsl */ `#version 300 es
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
uniform vec3 uMin;
uniform vec3 uSize;
out vec3 vWorld;
out vec3 vNormal;
${PROJECT}
void main() {
  vec3 p = uMin + (aPos + 0.5) * uSize;
  vWorld = p;
  vNormal = aNormal;
  gl_Position = project(p);
}
`

export const GLASS_FS = /* glsl */ `#version 300 es
precision highp float;
in vec3 vWorld;
in vec3 vNormal;
uniform vec3 uEye;
uniform vec3 uMin;
uniform vec3 uSize;
uniform sampler2D uLabel;
uniform vec4 uLabelRect;   // x0, z0, x1, z1 (world)
uniform vec4 uCoverRect;
out vec4 outColor;
void main() {
  vec3 n = normalize(vNormal);
  vec3 v = normalize(uEye - vWorld);
  float ndv = abs(dot(n, v));
  float fres = 0.04 + 0.96 * pow(1.0 - ndv, 5.0);
  vec3 r = reflect(-v, n);
  // A soft studio light reflected in the glass.
  float softbox = smoothstep(0.62, 0.96, r.y) * smoothstep(-0.85, 0.25, r.x);
  float side = 1.0 - step(0.5, abs(n.y));
  vec3 col = vec3(0.9, 0.93, 0.96);
  float a = 0.06 + fres * 0.35 + softbox * 0.12;
  // Soda-lime glass edges read green-grey.
  col = mix(col, vec3(0.56, 0.7, 0.67), side);
  a = mix(a, 0.5 + fres * 0.2, side);
  if (n.y > 0.5) {
    vec2 toEdge = min(vWorld.xz - uMin.xz, uMin.xz + uSize.xz - vWorld.xz);
    float rim = 1.0 - smoothstep(0.0, 0.01, min(toEdge.x, toEdge.y));
    col = mix(col, vec3(0.62, 0.69, 0.74), rim);
    a = max(a, rim * 0.55);
    vec2 lab = (vWorld.xz - uLabelRect.xy) / (uLabelRect.zw - uLabelRect.xy);
    if (all(greaterThanEqual(lab, vec2(0.0))) && all(lessThanEqual(lab, vec2(1.0)))) {
      vec4 label = texture(uLabel, lab);
      col = mix(col, label.rgb, label.a);
      a = mix(a, 0.97, label.a);
    }
    vec2 size = uCoverRect.zw - uCoverRect.xy;
    vec2 cov = (vWorld.xz - uCoverRect.xy);
    float inside = min(min(cov.x, size.x - cov.x), min(cov.y, size.y - cov.y));
    float coverEdge = 1.0 - smoothstep(0.0, 0.005, abs(inside));
    col = mix(col, vec3(0.66, 0.72, 0.78), coverEdge);
    a = max(a, coverEdge * 0.35);
  }
  outColor = vec4(col * a, a);
}
`

export const PLANE_VS = /* glsl */ `#version 300 es
layout(location = 0) in vec2 aPos;
uniform vec2 uOrigin;
uniform vec2 uExtent;
uniform float uY;
out vec2 vUv;
out vec3 vWorld;
${PROJECT}
void main() {
  vUv = aPos * 0.5 + 0.5;
  vec3 p = vec3(uOrigin.x + vUv.x * uExtent.x, uY, uOrigin.y + vUv.y * uExtent.y);
  vWorld = p;
  gl_Position = project(p);
}
`

/** Tissue on the glass, with the tile grid, scan line, attention overlay and emptied sockets. */
export const TISSUE_FS = /* glsl */ `#version 300 es
precision highp float;
in vec2 vUv;
in vec3 vWorld;
uniform sampler2D uSlide;
uniform sampler2D uTiles;   // r: score, g: rank (255 = none), b: valid
uniform vec2 uGrid;
uniform vec2 uGridOrigin;
uniform float uTile;
uniform vec2 uHover;
out vec4 outColor;
${INFERNO}
${TIMELINE}
void main() {
  vec4 tex = texture(uSlide, vUv);
  vec3 col = tex.rgb;
  float alpha = tex.a;
  vec2 g = (vWorld.xz - uGridOrigin) / uTile;
  vec2 cell = floor(g);
  vec2 f = fract(g);
  if (all(greaterThanEqual(cell, vec2(0.0))) && all(lessThan(cell, uGrid))) {
    vec4 data = texture(uTiles, (cell + 0.5) / uGrid);
    float valid = step(0.5, data.b);
    float score = data.r;
    float rank = floor(data.g * 255.0 + 0.5);
    vec2 d = min(f, 1.0 - f) / fwidth(g);
    float line = 1.0 - smoothstep(0.0, 1.2, min(d.x, d.y));
    float gridA = smoothstep(0.0, 0.1, uU) * (1.0 - smoothstep(0.88, 0.98, uU));
    col = mix(col, vec3(1.0), line * gridA * 0.5 * valid);
    float order = (cell.x + 0.5 + cell.y * 0.35) / (uGrid.x + uGrid.y * 0.35);
    float heat = scanAt(order) * valid * smoothstep(0.12, 0.6, score);
    float front = frontAt(order) * valid;
    col = mix(col, vec3(1.0), front * (line * 0.9 + 0.12));
    col = mix(col, inferno(0.18 + 0.7 * score), heat * 0.42);
    if (rank < 254.0) {
      float lift = liftAt(rank);
      col = mix(col, vec3(0.9, 0.92, 0.95), lift * 0.92);
      col = mix(col, vec3(0.0, 0.44, 0.89), lift * line);
    }
    float hover = (1.0 - step(0.1, distance(cell, uHover))) * valid;
    col = mix(col, vec3(1.0), hover * line);
    col += hover * 0.07;
  }
  outColor = vec4(col * alpha, alpha);
}
`

const ROTATE = /* glsl */ `
vec3 rotate(vec4 q, vec3 v) { return v + 2.0 * cross(q.xyz, cross(q.xyz, v) + q.w * v); }
`

/** Extracted patches: thin slabs that leave their sockets and gather in a gallery facing the viewer. */
export const PATCH_VS = /* glsl */ `#version 300 es
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec3 aPatch;   // col, row, rank
uniform float uTime;
uniform vec2 uGridOrigin;
uniform float uTile;
uniform vec3 uGallery;
uniform vec3 uRight;
uniform vec3 uUp;
uniform vec4 uRot;      // rotation from lying in the slide to facing the camera
out vec2 vTileUv;
out vec2 vLocalUv;
out float vLift;
out float vRank;
out float vTop;
out vec3 vNormal;
${PROJECT}
${TIMELINE}
${ROTATE}
void main() {
  float lift = liftAt(aPatch.z);
  float e = lift * lift * (3.0 - 2.0 * lift);
  vec2 centre = uGridOrigin + (aPatch.xy + 0.5) * uTile;
  int slot = int(aPatch.z + 0.5);
  float gx = float(slot % 4) - 1.5;
  float gy = 1.0 - float(slot / 4);
  float size = mix(uTile, 0.21, e);
  vec3 target = uGallery + uRight * gx * 0.245 + uUp * gy * 0.245 + uUp * sin(uTime * 1.3 + aPatch.z) * 0.008;
  vec3 start = vec3(centre.x, 0.0, centre.y);
  vec3 base = mix(start, target, e) + vec3(0.0, sin(e * 3.14159) * 0.18, 0.0);
  // Rigid turn from lying in the slide to facing the camera: slerp from identity to uRot.
  float halfAngle = acos(clamp(uRot.w, -1.0, 1.0));
  vec3 axis = uRot.xyz / max(sin(halfAngle), 1e-5);
  vec4 q = vec4(axis * sin(halfAngle * e), cos(halfAngle * e));
  float thick = mix(0.004, 0.012, e);
  vec3 local = vec3(aPos.x * size, (aPos.y + 0.5) * thick, aPos.z * size);
  vec3 p = base + rotate(q, local);
  vNormal = rotate(q, aNormal);
  vTileUv = aPatch.xy;
  vLocalUv = aPos.xz + 0.5;
  vLift = e;
  vRank = aPatch.z;
  vTop = step(0.5, aNormal.y);
  gl_Position = lift > 0.0005 ? project(p) : vec4(2.0, 2.0, 2.0, 1.0);
}
`

export const PATCH_FS = /* glsl */ `#version 300 es
precision highp float;
in vec2 vTileUv;
in vec2 vLocalUv;
in float vLift;
in float vRank;
in float vTop;
in vec3 vNormal;
uniform sampler2D uSlide;
uniform sampler2D uPatches;
uniform vec2 uSlideOrigin;
uniform vec2 uSlideExtent;
uniform vec2 uGridOrigin;
uniform float uTile;
out vec4 outColor;
void main() {
  vec2 world = uGridOrigin + (vTileUv + vLocalUv) * uTile;
  vec3 low = texture(uSlide, (world - uSlideOrigin) / uSlideExtent).rgb;
  // Integer cell maths: float mod() can return 4.0 for mod(4.0, 4.0) and sample outside the atlas.
  int slot = int(vRank + 0.5);
  vec2 cell = vec2(float(slot % 4), float(slot / 4));
  vec3 high = texture(uPatches, (cell + vLocalUv) / vec2(4.0, 3.0)).rgb;
  vec3 face = mix(low, high, smoothstep(0.35, 0.8, vLift));
  float border = min(min(vLocalUv.x, 1.0 - vLocalUv.x), min(vLocalUv.y, 1.0 - vLocalUv.y));
  face = mix(face, vec3(1.0), (1.0 - smoothstep(0.0, 0.02, border)) * vLift);
  float diffuse = 0.55 + 0.45 * max(dot(normalize(vNormal), normalize(vec3(0.3, 1.0, 0.5))), 0.0);
  outColor = vec4(mix(vec3(0.8, 0.83, 0.88) * diffuse, face, vTop), 1.0);
}
`

/** Thin links from each patch back to its socket while the gallery is shown. */
export const LINK_VS = /* glsl */ `#version 300 es
layout(location = 0) in float aEnd;
layout(location = 2) in vec3 aPatch;
uniform float uTime;
uniform vec2 uGridOrigin;
uniform float uTile;
uniform vec3 uGallery;
uniform vec3 uRight;
uniform vec3 uUp;
out float vAlpha;
${PROJECT}
${TIMELINE}
void main() {
  float lift = liftAt(aPatch.z);
  vec2 centre = uGridOrigin + (aPatch.xy + 0.5) * uTile;
  int slot = int(aPatch.z + 0.5);
  float gx = float(slot % 4) - 1.5;
  float gy = 1.0 - float(slot / 4);
  vec3 target = uGallery + uRight * gx * 0.245 + uUp * (gy * 0.245 - 0.105) + uUp * sin(uTime * 1.3 + aPatch.z) * 0.008;
  vec3 p = mix(vec3(centre.x, 0.002, centre.y), target, aEnd);
  vAlpha = smoothstep(0.85, 1.0, lift) * mix(0.55, 0.12, aEnd);
  gl_Position = project(p);
}
`

export const LINK_FS = /* glsl */ `#version 300 es
precision highp float;
in float vAlpha;
out vec4 outColor;
void main() { outColor = vec4(vec3(0.0, 0.44, 0.89) * vAlpha, vAlpha); }
`

/** Soft contact shadow under the slide, for a light page. */
export const GLOW_FS = /* glsl */ `#version 300 es
precision highp float;
in vec3 vWorld;
out vec4 outColor;
void main() {
  // World-space falloff that reaches zero well inside the quad, so no edge shows.
  vec2 q = vWorld.xz / vec2(1.7, 0.7);
  float g = exp(-dot(q, q) * 1.6) * 0.16;
  outColor = vec4(vec3(0.03, 0.05, 0.1) * g, g);
}
`
