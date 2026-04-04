class MinHeap {
  constructor() { this.data = []; }
  push(node) {
    this.data.push(node);
    this._bubbleUp(this.data.length - 1);
  }
  pop() {
    const top = this.data[0];
    const last = this.data.pop();
    if (this.data.length > 0) {
      this.data[0] = last;
      this._sinkDown(0);
    }
    return top;
  }
  get size() { return this.data.length; }
  _bubbleUp(i) {
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.data[i].f >= this.data[p].f) break;
      [this.data[i], this.data[p]] = [this.data[p], this.data[i]];
      i = p;
    }
  }
  _sinkDown(i) {
    const n = this.data.length;
    while (true) {
      let min = i;
      const l = 2 * i + 1, r = 2 * i + 2;
      if (l < n && this.data[l].f < this.data[min].f) min = l;
      if (r < n && this.data[r].f < this.data[min].f) min = r;
      if (min === i) break;
      [this.data[i], this.data[min]] = [this.data[min], this.data[i]];
      i = min;
    }
  }
}

const DIRS = [
  { dx: 0, dy: -1 }, { dx: 0, dy: 1 }, { dx: -1, dy: 0 }, { dx: 1, dy: 0 },
];

export function findPath(grid, startX, startY, endX, endY, dynamicBlocked = null) {
  const h = grid.length;
  const w = grid[0].length;

  if (startX < 0 || startX >= w || startY < 0 || startY >= h) return null;
  if (endX < 0 || endX >= w || endY < 0 || endY >= h) return null;
  if (grid[endY][endX] === 1) return null;

  const key = (x, y) => y * w + x;
  const heuristic = (x, y) => Math.abs(x - endX) + Math.abs(y - endY);

  const open = new MinHeap();
  const gScore = new Map();
  const cameFrom = new Map();

  const startKey = key(startX, startY);
  gScore.set(startKey, 0);
  open.push({ x: startX, y: startY, f: heuristic(startX, startY) });

  while (open.size > 0) {
    const curr = open.pop();
    const ck = key(curr.x, curr.y);

    if (curr.x === endX && curr.y === endY) {
      const path = [];
      let k = ck;
      while (k !== undefined) {
        const py = Math.floor(k / w);
        const px = k % w;
        path.unshift({ x: px, y: py });
        k = cameFrom.get(k);
      }
      return path;
    }

    const currG = gScore.get(ck);

    for (const dir of DIRS) {
      const nx = curr.x + dir.dx;
      const ny = curr.y + dir.dy;
      if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
      if (grid[ny][nx] === 1) continue;

      const nk = key(nx, ny);
      if (dynamicBlocked && dynamicBlocked.has(nk) && nk !== key(endX, endY)) continue;

      const ng = currG + 1;
      if (!gScore.has(nk) || ng < gScore.get(nk)) {
        gScore.set(nk, ng);
        cameFrom.set(nk, ck);
        open.push({ x: nx, y: ny, f: ng + heuristic(nx, ny) });
      }
    }
  }

  return null;
}

/** Find the entrance tile (bottom-center walkable tile) */
export function findEntrance(grid) {
  const midX = Math.floor(grid[0].length / 2);
  for (let y = grid.length - 1; y >= 0; y--) {
    for (let dx = 0; dx < 10; dx++) {
      if (midX + dx < grid[0].length && grid[y][midX + dx] === 0) return { x: midX + dx, y };
      if (midX - dx >= 0 && grid[y][midX - dx] === 0) return { x: midX - dx, y };
    }
  }
  return { x: midX, y: grid.length - 2 };
}
