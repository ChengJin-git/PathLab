import type { Geometry } from "../../api/viewer";

export function geometryValue({
  type,
  x,
  y,
  width,
  height,
  points,
  holes,
}: Geometry): Geometry {
  return { type, x, y, width, height, points, holes };
}
export function corners(r: Geometry): number[][] {
  return [
    [r.x, r.y],
    [r.x + r.width, r.y],
    [r.x + r.width, r.y + r.height],
    [r.x, r.y + r.height],
  ];
}
function ringArea(points: number[][]): number {
  return (
    Math.abs(
      points.reduce((sum, p, i) => {
        const q = points[(i + 1) % points.length];
        return sum + p[0] * q[1] - p[1] * q[0];
      }, 0),
    ) / 2
  );
}
export function geometryArea(r: Geometry): number {
  return r.type === "rect"
    ? r.width * r.height
    : Math.max(
        0,
        ringArea(r.points || []) -
          (r.holes || []).reduce((sum, ring) => sum + ringArea(ring), 0),
      );
}
function inRing([x, y]: number[], points: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i],
      [xj, yj] = points[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}
export function containsPoint(r: Geometry, point: number[]): boolean {
  if (
    point[0] < r.x ||
    point[0] > r.x + r.width ||
    point[1] < r.y ||
    point[1] > r.y + r.height
  )
    return false;
  return (
    r.type === "rect" ||
    (inRing(point, r.points || []) &&
      !(r.holes || []).some((ring) => inRing(point, ring)))
  );
}
