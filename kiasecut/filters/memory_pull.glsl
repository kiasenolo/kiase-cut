// @filter 記憶體被拔出
// @category 風格
// @description 像記憶體突然被拔掉：畫面當成一塊塊記憶體分頁，壞掉的分頁變成用底下畫面讀錯位址、錯行寬、重複一小段、顏色亂掉的花屏（也可以改成空值），旁邊的分頁讀到錯的位址、位元翻轉，越壞越多
// @param amount float 1 0 1 "損壞程度"
// @param spread bool true "隨時間擴大"
// @param page float 1024 16 65536 "分頁大小（像素）"
// @param stale float 0.3 0 1 "讀錯位址"
// @param flips float 0.3 0 1 "位元翻轉"
// @param null_look menu 花屏 "花屏|透明|黑色|白色" "壞掉的分頁"
// @param rate float 12 0 60 "每秒變化"
// @param seed float 0 0 100 "種子"

// The picture is read as memory: pixel (x, y) of the canvas is address y * width + x, in pages
// of `page` pixels. Each page has its own moment to fail (spread: over the effect's length,
// failing pages stay failed). A failed page shows garbage made of what is under it (花屏): the
// picture read with a wrong row width (it tears diagonally), a few words read again and again
// (streaks), the pixels of somewhere else, with the colours mixed up or cut to a few bits - or
// reads as nothing at all (0: transparent black, or black / white). A page next to failing ones
// may read another page's pixels (a wrong address) or come back with bits flipped. `rate` is how
// often the misreads change, a second.

float h1(float a, float b) { return fract(sin(a * 12.9898 + b * 78.233 + seed * 1.731) * 43758.5453); }

// what a failed page shows: the picture under it, read wrongly
vec4 garble(float addr, float pg, float tick, vec2 px) {
    float W = resolution.x, N = resolution.x * resolution.y;
    float start = pg * max(page, 1.0);
    float k = h1(pg + tick * 0.37, 11.0);
    float a2 = addr;
    if (k < 0.35) {                                         // a wrong row width: the rows slide into each other
        float W2 = max(W + floor((h1(pg, 12.0) - 0.5) * 96.0), 8.0);
        vec2 q = vec2(mod(addr, W2), floor(addr / W2));
        a2 = q.y * W + q.x;
    } else if (k < 0.65) {                                  // the same few words again and again
        float chunk = floor(mix(8.0, 900.0, h1(pg, 13.0) * h1(pg, 14.0)));
        a2 = start + mod(addr - start, max(chunk, 1.0));
    } else {                                                // somewhere else in memory
        a2 = addr + floor((h1(pg, tick + 15.0) - 0.5) * 2.0 * N * 0.5);
    }
    if (h1(px.y + pg * 0.13, tick + 16.0) < 0.25)           // a few rows come in late
        a2 += floor((h1(px.y, tick + 17.0) - 0.5) * 2.0 * 160.0);
    a2 = mod(a2, N);
    vec2 p2 = vec2(mod(a2, W), floor(a2 / W)) + 0.5;
    vec4 c = src(p2 / resolution);
    vec4 u = unpremultiply(c);
    float m = h1(pg, 18.0);
    if (m < 0.25) u.rgb = u.gbr;                            // colours mixed up
    else if (m < 0.45) u.rgb = u.brg;
    else if (m < 0.60) u.rgb = 1.0 - u.rgb;
    else if (m < 0.80) {                                    // cut to a few bits
        ivec3 b = ivec3(clamp(u.rgb, 0.0, 1.0) * 255.0 + 0.5);
        int keep = (m < 0.7) ? 0xC0 : 0xE0;
        b = b & ivec3(keep);
        u.rgb = vec3(b) / 255.0;
    }
    return premultiply(vec4(clamp(u.rgb, 0.0, 1.0), u.a));
}

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
        if (null_look == 2) return vec4(0.0, 0.0, 0.0, 1.0);
        if (null_look == 3) return vec4(1.0);
        if (null_look == 1) return vec4(0.0);               // CPU reads only 0
        return garble(addr, pg, tick, px);
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
