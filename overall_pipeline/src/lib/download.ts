const SVG_NS = 'http://www.w3.org/2000/svg'

function serialize(svg: SVGSVGElement): string {
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', SVG_NS)
  clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink')
  const [, , w, h] = viewBox(svg)
  clone.setAttribute('width', String(w))
  clone.setAttribute('height', String(h))
  return new XMLSerializer().serializeToString(clone)
}

function viewBox(svg: SVGSVGElement): [number, number, number, number] {
  const parts = (svg.getAttribute('viewBox') ?? '0 0 1000 1000').split(/\s+/).map(Number)
  return [parts[0], parts[1], parts[2], parts[3]]
}

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function downloadSvg(svg: SVGSVGElement | null, filename: string) {
  if (!svg) return
  save(new Blob([serialize(svg)], { type: 'image/svg+xml;charset=utf-8' }), filename)
}

export function downloadPng(svg: SVGSVGElement | null, filename: string, scale = 2) {
  if (!svg) return
  const [, , w, h] = viewBox(svg)
  const source = new Blob([serialize(svg)], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(source)
  const img = new Image()

  img.onload = () => {
    const canvas = document.createElement('canvas')
    canvas.width = w * scale
    canvas.height = h * scale
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    // Paper figures assume an opaque sheet — never export a transparent ground.
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    URL.revokeObjectURL(url)
    canvas.toBlob((blob) => blob && save(blob, filename), 'image/png')
  }
  img.onerror = () => URL.revokeObjectURL(url)
  img.src = url
}
