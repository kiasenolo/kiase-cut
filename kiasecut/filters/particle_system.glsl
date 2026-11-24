// @filter 粒子系統
// @nodes
// @category 粒子
// @description 通用的粒子系統：發射器（點、線、圓、矩形、圖片）、重力／風／阻力／亂流／地面反彈、隨生命變化的大小和顏色、各種粒子形狀、拖尾；火花、雪、煙火、光點都能用它做。套在透明的片段上就是一個粒子物件，套在有圖片的片段上可以從圖片噴出粒子
// @particles 200000 count*(trail+1)+count*sub
// @sprite sprite_img
// @param count int 400 1 20000 "粒子數"
// @param mode menu 持續 "持續|爆發" "發射方式"
// @param life float 2 0.1 30 "壽命（秒）"
// @param life_var float 0.3 0 1 "壽命差異"
// @param period float 4 0.2 60 "爆發間隔（秒）"
// @enable period mode == 爆發
// @param time_offset float 0 0 120 "時間偏移（秒）"
// @param seed float 0 0 100 "種子"
// @panel 發射器
// @param emitter menu 點 "點|線|圓形|矩形|圖片|球體" "形狀"
// @param origin_x float 0.5 -1 2 "位置 X（0 左、1 右）"
// @param origin_y float 0.5 -1 2 "位置 Y（0 上、1 下）"
// @param ewidth float 400 0 4000 "寬（像素）"
// @param eheight float 300 0 4000 "高（像素）"
// @param erot float 0 -360 360 "旋轉（度）"
// @param threshold float 0.1 0 1 "透明度門檻"
// @param tint bool true "顏色取自圖片"
// @param hide_src bool false "隱藏原畫面"
// @enable ewidth emitter != 點|圖片
// @enable eheight emitter == 矩形
// @enable erot emitter != 點|圖片
// @enable threshold emitter == 圖片
// @enable tint emitter == 圖片
// @enable hide_src emitter == 圖片
// @panel 運動
// @param outward bool false "從發射位置向外"
// @param angle float 0 -360 360 "方向（度，0 向上）"
// @param spread float 360 0 360 "散開角度"
// @param speed float 250 0 4000 "初速（像素／秒）"
// @param speed_var float 0.5 0 1 "初速差異"
// @enable angle !outward
// @enable spread !outward
// @panel 力
// @param gravity float 300 -3000 3000 "重力（像素／秒²）"
// @param wind float 0 -2000 2000 "風（像素／秒²）"
// @param drag float 0.3 0 10 "空氣阻力"
// @param turb float 0 0 500 "亂流（像素）"
// @param turb_scale float 200 10 2000 "亂流大小（像素）"
// @param turb_speed float 0.5 0 5 "亂流速度"
// @param floor_on bool false "地面（反彈）"
// @param floor_y float 0.9 0 1 "地面高度（0 上、1 下）"
// @param bounce float 0.5 0 1 "彈性"
// @enable floor_y floor_on
// @enable bounce floor_on
// @enable turb_scale turb
// @enable turb_speed turb
// @panel 3D
// @param depth_on bool false "3D（透視）"
// @param persp float 50 10 120 "透視視角（度）"
// @param origin_z float 0 -2000 2000 "位置 Z（像素，正值是遠）"
// @param ethick float 0 0 4000 "發射器厚度（像素）"
// @param speed_z float 0 -3000 3000 "Z 方向初速（像素／秒）"
// @param zspread float 0 0 1 "Z 方向散開"
// @param gravity_z float 0 -3000 3000 "Z 方向的力（像素／秒²）"
// @param fog float 0 0 1 "遠處變淡"
// @enable persp depth_on
// @enable origin_z depth_on
// @enable ethick depth_on
// @enable speed_z depth_on
// @enable zspread depth_on
// @enable gravity_z depth_on
// @enable fog depth_on
// @panel 外觀
// @param look menu 柔邊圓 "柔邊圓|實心圓|方塊|多邊形|星芒|線條|圖片" "形狀"
// @param sides int 5 3 12 "邊數"
// @param softness float 0.6 0 1 "柔邊"
// @param sprite_img color #ffffff "粒子圖片"
// @param pic_colors bool true "用圖片原本的顏色"
// @param size float 12 0.5 300 "大小（像素）"
// @param size_var float 0.4 0 1 "大小差異"
// @param size_end float 0.3 0 4 "結束時大小（倍）"
// @param size_curve curve 0,0,1,1 "大小變化曲線"
// @param aspect float 1 0.2 8 "長寬比（方塊）"
// @param stretch float 0 0 0.5 "依速度拉長（秒）"
// @param rotmode menu 固定 "固定|隨機|旋轉|順著運動" "朝向"
// @param spin float 2 -30 30 "旋轉速度"
// @param flip float 0 0 30 "翻面速度（方塊翻動時變窄）"
// @param colors gradient 0:#fff3c4,0.5:#ffa43a,1:#ff3b1a "顏色"
// @param color_mode menu 隨生命 "隨生命|每個隨機" "顏色怎麼挑"
// @param alpha float 1 0 1 "不透明度"
// @param fade_in float 0.05 0 1 "淡入（占壽命）"
// @param fade_out float 0.4 0 1 "淡出（占壽命）"
// @param brightness float 1 0 8 "亮度"
// @param glow float 1 0 1 "發光（疊加）"
// @param twinkle float 0 0 1 "閃爍"
// @enable sides look == 多邊形
// @enable aspect look == 方塊
// @enable softness look == 柔邊圓
// @enable sprite_img look == 圖片
// @enable pic_colors look == 圖片
// @enable spin rotmode == 旋轉
// @panel 拖尾
// @param trail int 0 0 16 "拖尾段數"
// @param trail_step float 0.03 0.005 0.3 "段與段的間隔（秒）"
// @param trail_fade float 0.8 0 1 "尾巴變淡"
// @enable trail_step trail
// @enable trail_fade trail
// @panel 子粒子
// @param sub int 0 0 40 "每個粒子生出幾個"
// @param sub_mode menu 沿路徑 "沿路徑|死亡時|出生時" "什麼時候生"
// @param sub_from float 0.2 0 1 "路徑上從（占壽命）"
// @param sub_to float 0.9 0 1 "路徑上到（占壽命）"
// @param sub_life float 0.8 0.05 10 "子粒子壽命（秒）"
// @param sub_speed float 90 0 3000 "子粒子初速（像素／秒）"
// @param sub_inherit float 0.3 0 1 "繼承父粒子的速度"
// @param sub_size float 4 0.5 100 "子粒子大小（像素）"
// @param sub_size_end float 0.2 0 4 "結束時大小（倍）"
// @param sub_colors gradient 0:#ffffff,0.4:#ffcf6a,1:#ff5a1f "子粒子顏色（隨生命）"
// @enable sub_mode sub
// @enable sub_from sub_mode == 沿路徑
// @enable sub_to sub_mode == 沿路徑
// @enable sub_life sub
// @enable sub_speed sub
// @enable sub_inherit sub
// @enable sub_size sub
// @enable sub_size_end sub
// @enable sub_colors sub
// @step 10 ewidth eheight speed gravity wind turb turb_scale

// A general particle system, stateless like sparks.glsl: where particle i is follows from its number, the time and the settings,
// so any frame is drawn on its own. Slot i is born again every `life` seconds (staggered by i / count) or, as a burst, all of
// them every `period` seconds; `k` (which birth it is) is part of every random number, so each birth is different.
// Motion is closed form: v' = acceleration - drag v; with 地面 the vertical motion bounces off the floor (without drag) and
// 亂流 adds a smooth displacement. A trail is the same particle drawn at `trail` earlier moments, a sub-particle one born where its
// parent was at some moment of its life (the parent's position then is as easy to work out as now): instances are
// [count * (trail + 1) parents and their trails][count * sub children] - instance = particle * (trail + 1) + copy, then parent * sub + child.
// With sub-particles a continuous slot lasts `life` + the children's life, so the children of a parent that has died can finish.
// Not here, because they need what other particles or the picture did: collisions between particles, pushing by the picture.

float R(int i, float k, float salt) {
    return rand(vec2(float(i) * 0.6180339 + seed * 3.7 + salt * 11.3, k * 1.7321 + salt * 5.11 + 0.5));
}

float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(rand(i), rand(i + vec2(1.0, 0.0)), f.x), mix(rand(i + vec2(0.0, 1.0)), rand(i + vec2(1.0, 1.0)), f.x), f.y);
}

float K() { return resolution.y / 1080.0; }                       // (the lengths are px of a 1080-high canvas: the same look at any size)

vec2 turn(vec2 v, float a) { float c = cos(a), s = sin(a); return vec2(c * v.x - s * v.y, s * v.x + c * v.y); }

vec4 effect(vec2 uv) {
    return (hide_src && emitter == 4) ? vec4(0.0) : src(uv);
}

// a parent particle's birth: how far into its slot it is (s), which birth (k), its life, where it starts and how fast, the picture's colour there
struct Born { float s; float k; float lf; vec2 base; vec2 v0; vec4 pic; float bz; float vz; };

bool born(int i, out Born b) {
    float tt = time + time_offset;
    float slot = (mode == 0 && sub > 0) ? life + sub_life : life;
    float s, k;
    if (mode == 0) {
        s = tt - float(i) * slot / float(count);
        if (s < 0.0) return false;
        k = floor(s / slot);
        s -= k * slot;
    } else {
        k = floor(tt / period);
        s = tt - k * period;
    }
    b.s = s;
    b.k = k;
    b.lf = life * (1.0 - life_var * R(i, k, 1.0));

    vec2 centre = vec2(origin_x, origin_y) * resolution;
    b.base = centre;
    float zoff = 0.0;
    vec3 out3 = vec3(0.0);
    b.pic = vec4(1.0);
    float ra = R(i, k, 2.0), rb = R(i, k, 3.0);
    if (emitter == 1) {
        b.base += turn(vec2((ra - 0.5) * ewidth * K(), 0.0), radians(erot));
    } else if (emitter == 2) {
        float rr = 0.5 * ewidth * K() * sqrt(ra), ang = rb * 6.2831853;
        b.base += turn(vec2(cos(ang), sin(ang)) * rr, radians(erot));
    } else if (emitter == 3) {
        b.base += turn(vec2((ra - 0.5) * ewidth, (rb - 0.5) * eheight) * K(), radians(erot));
    } else if (emitter == 5) {                                     // a ball (in 3D; a disc seen flat): anywhere inside it
        float rc = R(i, k, 16.0), ct = 2.0 * rb - 1.0, st = sqrt(max(0.0, 1.0 - ct * ct)), ph = 6.2831853 * rc;
        out3 = vec3(st * cos(ph), st * sin(ph), ct);
        float rr = 0.5 * ewidth * K() * pow(ra, 1.0 / 3.0);
        b.base += out3.xy * rr;
        zoff = out3.z * rr;
    } else if (emitter == 4) {                                     // anywhere the picture is there: a few tries
        bool found = false;
        for (int t = 0; t < 12; t++) {
            vec2 q = vec2(R(i, k, 20.0 + float(t)), R(i, k, 40.0 + float(t)));
            vec4 c = src(q);
            if (c.a > threshold) {
                b.base = q * resolution;
                b.pic = c.a > 0.0 ? vec4(c.rgb / c.a, c.a) : vec4(1.0);
                found = true;
                break;
            }
        }
        if (!found) return false;
        centre = 0.5 * resolution;
    }
    vec2 dir;
    vec2 away = b.base - centre;
    if (outward && length(away) > 0.5) {
        dir = normalize(away);
    } else {
        float a = radians(angle + (R(i, k, 4.0) - 0.5) * spread);
        dir = vec2(sin(a), -cos(a));
    }
    b.v0 = dir * speed * K() * (1.0 - speed_var * R(i, k, 5.0));
    b.bz = origin_z * K() + zoff + (R(i, k, 14.0) - 0.5) * ethick * K();             // (Z: away from the viewer; only with 3D)
    b.vz = speed_z * K() + zspread * speed * K() * (R(i, k, 15.0) * 2.0 - 1.0);
    if (outward && emitter == 5) b.vz += out3.z * speed * K() * (1.0 - speed_var * R(i, k, 5.0));      // (away from the middle of the ball, in Z too)
    return true;
}

// the depth of a particle that starts at bz going vz, s seconds on (the same law as the plane: v' = a - drag v), and how fast it goes in Z
void movez(float bz, float vz, float s, out float z, out float v) {
    float a = gravity_z * K();
    if (drag > 0.001) {
        float vt = a / drag, e = exp(-drag * s);
        v = vt + (vz - vt) * e;
        z = bz + vt * s + (vz - vt) * (1.0 - e) / drag;
    } else {
        v = vz + a * s;
        z = bz + vz * s + 0.5 * a * s * s;
    }
}

// where a particle that starts at base with velocity v0 is s seconds on, and how fast it goes
void move(vec2 base, vec2 v0, float s, out vec2 pos, out vec2 vel) {
    vec2 acc = vec2(wind, gravity) * K();
    pos = base;
    if (drag > 0.001) {
        vec2 vt = acc / drag;
        float e = exp(-drag * s);
        vel = vt + (v0 - vt) * e;
        pos += vt * s + (v0 - vt) * (1.0 - e) / drag;
    } else {
        vel = v0 + acc * s;
        pos += v0 * s + 0.5 * acc * s * s;
    }
    if (floor_on && gravity > 0.0) {
        float gk = gravity * K();                               // the vertical motion again, bouncing (no drag)
        float fy = floor_y * resolution.y;
        float y = base.y, vy = v0.y, left = s;
        for (int b = 0; b < 8; b++) {
            float c = y - fy;                                      // (above the floor: negative)
            float disc = vy * vy - 2.0 * gk * c;
            float th = c >= 0.0 ? 0.0 : (-vy + sqrt(max(disc, 0.0))) / gk;
            if (th > left || (c >= 0.0 && abs(vy) < 1.0)) break;
            left -= th;
            vy = -(vy + gk * th) * bounce;
            y = fy;
            if (abs(vy) < 4.0) { vy = 0.0; break; }
        }
        float below = y - fy;
        pos.y = below >= 0.0 && vy == 0.0 ? fy : y + vy * left + 0.5 * gk * left * left;
        pos.y = min(pos.y, fy);
        vel.y = vy + gk * left;
    }
    if (turb > 0.0) {
        vec2 q = pos / (turb_scale * K());
        float tz = (time + time_offset) * turb_speed;
        pos += turb * K() * (1.0 - exp(-3.0 * s)) * (vec2(vnoise(q + vec2(tz, 0.0)), vnoise(q + vec2(17.3, tz))) - 0.5) * 2.0;
    }
}

bool particle(int id, out Particle p) {
    float tt = time + time_offset;
    int copies = trail + 1;
    int parents = count * copies;
    bool child = id >= parents;
    Born b;
    int i, j = 0, copy = 0;
    float s, lf, k, sz, fade_t = 1.0;
    vec2 pos, vel;
    float z = 0.0, vz;
    vec4 c;
    if (!child) {
        i = id / copies;
        copy = id - i * copies;
        if (!born(i, b)) return false;
        k = b.k;
        lf = b.lf;
        s = b.s - float(copy) * trail_step;                        // a trail copy: the same particle, a little earlier
        if (s < 0.0 || s >= lf) return false;
        move(b.base, b.v0, s, pos, vel);
        if (depth_on) movez(b.bz, b.vz, s, z, vz);
        fade_t = 1.0 - trail_fade * float(copy) / float(copies);
    } else {
        int n = id - parents;
        i = n / sub;
        j = n - i * sub;
        if (!born(i, b)) return false;
        k = b.k;
        float fj = float(j);
        float tau = sub_mode == 1 ? b.lf : sub_mode == 2 ? 0.0
                  : b.lf * mix(sub_from, sub_to, (fj + R(i, k, 60.0 + fj)) / float(sub));      // when, in the parent's life, it is born
        lf = sub_life * (1.0 - life_var * R(i, k, 80.0 + fj));
        s = b.s - tau;
        if (s < 0.0 || s >= lf) return false;
        vec2 at, vat;
        move(b.base, b.v0, min(tau, b.lf), at, vat);               // the parent, where it was then
        float zat = 0.0, vzat = 0.0;
        if (depth_on) movez(b.bz, b.vz, min(tau, b.lf), zat, vzat);
        float a = R(i, k, 100.0 + fj) * 6.2831853;
        vec2 v0 = vat * sub_inherit + vec2(cos(a), sin(a)) * sub_speed * K() * (1.0 - speed_var * R(i, k, 120.0 + fj));
        move(at, v0, s, pos, vel);
        if (depth_on) movez(zat, vzat * sub_inherit, s, z, vz);
    }
    float u = s / lf;
    float jr = child ? 40.0 + float(j) : 0.0;                      // (a child's own random numbers)

    // how it looks
    if (child) {
        sz = sub_size * K() * (1.0 - size_var * R(i, k, 6.0 + jr)) * mix(1.0, sub_size_end, curve_ease(size_curve, u));
        c = gradient_eval(sub_colors_p, sub_colors_c, sub_colors_n, u, 2, 0, 0);
    } else {
        sz = size * K() * (1.0 - size_var * R(i, k, 6.0)) * mix(1.0, size_end, curve_ease(size_curve, u));
        c = gradient_eval(colors_p, colors_c, colors_n, color_mode == 1 ? R(i, k, 12.0) : u, color_mode == 1 ? 4 : 2, 0, 0);
        if (emitter == 4 && tint) c.rgb *= b.pic.rgb;
    }
    float spd = length(vel);
    vec2 heading = spd > 0.001 ? vel / spd : vec2(1.0, 0.0);
    p.rot = rotmode == 1 ? R(i, k, 7.0 + jr) * 6.2831853 : rotmode == 2 ? R(i, k, 7.0 + jr) * 6.2831853 + spin * s : atan(heading.y, heading.x);
    p.size = vec2(sz);
    if (look == 6 && has_sprite_picture()) {                       // a picture: its own shape, its long side sz
        vec2 ps = sprite_picture_size();
        float ratio = ps.x / max(ps.y, 1.0);
        p.size = ratio >= 1.0 ? vec2(sz, sz / ratio) : vec2(sz * ratio, sz);
    }
    if (look == 2) p.size.x *= aspect;
    p.pos = pos;
    if (look == 5 || stretch > 0.0) {                              // a streak: along the motion, the head where the particle is
        float half_len = sz + 0.5 * spd * (look == 5 ? max(stretch, 0.04) : stretch);
        p.rot = atan(heading.y, heading.x);
        p.size = vec2(half_len, look == 5 ? sz * 0.5 : sz);
        p.pos = pos - heading * (half_len - sz);
    } else if (rotmode == 0) {
        p.rot = 0.0;
    }
    float near_fade = 1.0;
    if (scene_f > 0.0) {                                           // in a 3D 場景: through the scene's camera, from the clip's own place and turn
        vec2 mid = 0.5 * resolution;
        vec4 cs = scene_m * vec4(p.pos - mid, depth_on ? z : 0.0, 1.0);
        if (cs.z <= 0.0005 * resolution.y) return false;           // (behind the camera)
        float sc = scene_f / cs.z;
        p.pos = mid + cs.xy * sc;
        p.size *= sc;
        near_fade = mix(1.0, clamp(sc * scene_m[3].z / scene_f, 0.0, 1.0), fog);
    } else if (depth_on) {                                         // perspective about the middle of the picture: farther is smaller, nearer bigger
        float d = 0.5 * resolution.y / tan(radians(persp) * 0.5);
        if (d + z < 0.05 * d) return false;                        // (behind the viewer)
        float sc = d / (d + z);
        vec2 mid = 0.5 * resolution;
        p.pos = mid + (p.pos - mid) * sc;
        p.size *= sc;
        near_fade = mix(1.0, clamp(sc, 0.0, 1.0), fog);
    }
    float facing = 1.0;
    if (flip > 0.0 && look != 5 && stretch <= 0.0) {               // turning over: narrower, and darker on the back
        facing = cos(R(i, k, 11.0 + jr) * 6.2831853 + flip * s * (0.5 + R(i, k, 13.0 + jr)));
        p.size.y *= max(abs(facing), 0.08);
    }

    float fin = fade_in > 0.0 ? smoothstep(0.0, fade_in, u) : 1.0;
    float fout = fade_out > 0.0 ? 1.0 - smoothstep(1.0 - fade_out, 1.0, u) : 1.0;
    float tw = 1.0 - twinkle * (0.5 + 0.5 * sin(tt * (8.0 + 10.0 * R(i, k, 8.0 + jr)) + 60.0 * R(i, k, 9.0 + jr)));
    c.rgb *= brightness * tw;
    c.a *= alpha * fin * fout * fade_t * near_fade;
    p.color = c;
    p.data = vec4(u, facing, 1.5 / max(min(p.size.x, p.size.y), 1.0), brightness * tw);
    return true;
}

vec4 sprite(vec2 q, vec4 color, vec4 data) {
    float a;
    float soft = data.z;
    if (look == 0) {                                               // a soft glow
        float d = length(q);
        a = exp(-d * d * (1.0 + (1.0 - softness) * 7.0)) * (1.0 - smoothstep(0.85, 1.0, d));
    } else if (look == 1) {
        a = 1.0 - smoothstep(1.0 - soft, 1.0, length(q));
    } else if (look == 2) {
        vec2 e = (1.0 - abs(q)) / soft;
        a = clamp(min(e.x, e.y), 0.0, 1.0);
        if (flip > 0.0) {
            float light = (data.y > 0.0 ? 1.0 : 0.72) * mix(1.0, abs(data.y), 0.4);
            return vec4(color.rgb * light * color.a * a, color.a * a * (1.0 - glow));
        }
    } else if (look == 3) {
        float seg = 6.2831853 / float(sides);
        float t = mod(atan(q.y, q.x) + 6.2831853, seg) - 0.5 * seg;
        a = 1.0 - smoothstep(1.0 - soft, 1.0, length(q) / (cos(0.5 * seg) / cos(t)));
    } else if (look == 4) {                                        // a four-pointed sparkle
        vec2 w = abs(q);
        float cross_ = max((1.0 - w.x) * exp(-w.y * 14.0), (1.0 - w.y) * exp(-w.x * 14.0));
        a = clamp(cross_ + exp(-dot(q, q) * 10.0) * 0.8, 0.0, 1.0) * (1.0 - smoothstep(0.9, 1.0, max(w.x, w.y)));
    } else if (look == 6) {                                        // a picture (a soft dot while there is none)
        if (!has_sprite_picture()) {
            a = 1.0 - smoothstep(0.5, 1.0, length(q));
        } else {
            vec4 c = sprite_picture(q);
            vec3 rgb = pic_colors ? c.rgb * data.w : c.rgb * color.rgb;     // (the colour has the brightness and the flicker in it)
            return vec4(rgb * color.a, c.a * color.a * (1.0 - glow));
        }
    } else {                                                       // a streak: dim tail, bright head
        float across = 1.0 - smoothstep(0.0, 1.0, abs(q.y));
        across *= across;
        float along = mix(0.2, 1.0, smoothstep(-1.0, 1.0, q.x) * smoothstep(-1.0, 1.0, q.x));
        a = across * along * smoothstep(-1.0, -0.6, q.x) * (1.0 - smoothstep(0.75, 1.0, q.x));
    }
    return vec4(color.rgb * color.a * a, color.a * a * (1.0 - glow));
}
