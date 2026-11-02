// @filter 記憶體被拔出
// @category 風格
// @description 像記憶體突然被拔掉：畫面當成一塊塊記憶體分頁，壞掉的分頁 CPU 只讀得到空值（0），旁邊的分頁讀到錯的位址、位元翻轉，越壞越多
// @param amount float 1 0 1 "損壞程度"
// @param spread bool true "隨時間擴大"
// @param page float 1024 16 65536 "分頁大小（像素）"
// @param stale float 0.3 0 1 "讀錯位址"
// @param flips float 0.3 0 1 "位元翻轉"
// @param null_look menu 透明 "透明|黑色|白色" "空值顯示"
// @param rate float 12 0 60 "每秒變化"
// @param seed float 0 0 100 "種子"

// The picture is read as memory: pixel (x, y) of the canvas is address y * width + x, in pages
// of `page` pixels. Each page has its own moment to fail (spread: over the effect's length,
// failing pages stay failed); a failed page reads as nothing at all (0: transparent black, or
// black / white); a page next to failing ones may read another page's pixels (a wrong address)
// or come back with bits flipped. `rate` is how often the misreads change, a second.

float h1(float a, float b) { return fract(sin(a * 12.9898 + b * 78.233 + seed * 1.731) * 43758.5453); }

vec4 effect(vec2 uv) {
    vec2 px = floor(uv * resolution);
    float W = resolution.x;
    float addr = px.y * W + px.x;
    float pg = floor(addr / max(page, 1.0));
    float pages = ceil(resolution.x * resolution.y / max(page, 1.0));
    float cover = clamp(amount, 0.0, 1.0) * (spread ? clamp(progress * 1.15, 0.0, 1.0) : 1.0);
    float tick = floor(time * rate);
    // when this page fails: neighbouring pages tend to go together (whole chips), with some scatter
    float chip = floor(pg / 64.0);
    float fail = 0.7 * h1(chip, 1.0) + 0.3 * h1(pg, 2.0);
    if (fail < cover) {
        if (null_look == 1) return vec4(0.0, 0.0, 0.0, 1.0);
        if (null_look == 2) return vec4(1.0);
        return vec4(0.0);                                   // CPU reads only 0
    }
    vec4 c = src(uv);
    float near = smoothstep(cover + 0.25, cover, fail);  // close to failing: unreliable
    // a wrong address: the pixels of another page (a few pages away, or the same offset in a far one)
    if (h1(pg + tick * 0.37, 3.0) < stale * near) {
        float jump = floor((h1(pg, tick + 4.0) - 0.5) * 2.0 * min(pages, 512.0));
        float a2 = mod(addr + jump * page, resolution.x * resolution.y);
        vec2 p2 = vec2(mod(a2, W), floor(a2 / W)) + 0.5;
        c = src(p2 / resolution);
    }
    // bits flipped: a channel's byte with one bit turned over
    if (h1(addr * 0.0137 + tick, 5.0) < flips * near * 0.5) {
        vec4 u = unpremultiply(c);
        ivec4 b = ivec4(clamp(u, 0.0, 1.0) * 255.0 + 0.5);
        int ch = int(h1(addr, tick + 6.0) * 4.0) % 4;
        int bit = 1 << int(h1(addr, tick + 7.0) * 8.0);
        b[ch] = b[ch] ^ bit;
        c = premultiply(vec4(b) / 255.0);
    }
    return c;
}
