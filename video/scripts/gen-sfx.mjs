// Synthesizes the film's sound-design palette with ffmpeg (deterministic, no assets needed).
// Replace any file in public/audio/sfx with a recorded sound of the same name to upgrade it.
import { execSync } from "node:child_process";
import fs from "node:fs";

const OUT = "public/audio/sfx";
fs.mkdirSync(OUT, { recursive: true });

const ev = (expr, d, post = "") =>
  `-f lavfi -i "aevalsrc=exprs='${expr}|${expr}':s=48000:d=${d}"${post ? ` -af "${post}"` : ""}`;

const SFX = {
  tick: ev("0.5*sin(2*PI*1760*t)*exp(-90*t)+0.2*sin(2*PI*3520*t)*exp(-140*t)", 0.12),
  tap: ev("0.7*sin(2*PI*520*t)*exp(-40*t)+0.3*sin(2*PI*1040*t)*exp(-60*t)", 0.2, "highpass=f=200"),
  impact: ev("0.9*sin(2*PI*(58+40*exp(-18*t))*t)*exp(-7*t)", 0.7, "lowpass=f=900"),
  pluck: ev("0.55*sin(2*PI*392*t)*exp(-3.5*t)+0.22*sin(2*PI*784*t)*exp(-6*t)+0.1*sin(2*PI*1176*t)*exp(-9*t)", 1.6, "aecho=0.8:0.6:120|240:0.25|0.15"),
  swell: ev("(0.14*sin(2*PI*220*t)+0.1*sin(2*PI*329.63*t)+0.08*sin(2*PI*440*t))*(t/1.6)*(t/1.6)", 1.8, "afade=t=out:st=1.5:d=0.3,aecho=0.8:0.7:180:0.3"),
  resolve: ev("(0.16*sin(2*PI*261.63*t)+0.12*sin(2*PI*329.63*t)+0.1*sin(2*PI*392*t)+0.07*sin(2*PI*523.25*t))*exp(-1.2*t)*(1-exp(-40*t))", 3, "aecho=0.8:0.7:200|400:0.3|0.2"),
  reject: ev("0.35*sin(2*PI*(330-120*t)*t)*exp(-7*t)", 0.5, "lowpass=f=1500"),
  low: ev("(0.4*sin(2*PI*55*t)+0.18*sin(2*PI*110*t)+0.06*sin(2*PI*164.81*t))*exp(-0.6*t)*(1-exp(-8*t))", 6, "aecho=0.8:0.7:300:0.25"),
  whoosh: `-f lavfi -i "anoisesrc=c=pink:d=1.1:a=0.5:seed=7" -af "highpass=f=250,lowpass=f=2600,afade=t=in:d=0.6:curve=qsin,afade=t=out:st=0.6:d=0.5:curve=qsin,volume=0.6"`,
  shimmer: `-f lavfi -i "anoisesrc=c=white:d=1.4:a=0.25:seed=3" -af "highpass=f=5000,afade=t=in:d=0.5,afade=t=out:st=0.6:d=0.8,aecho=0.8:0.6:90:0.3,volume=0.5"`,
};

for (const [name, args] of Object.entries(SFX)) {
  execSync(`ffmpeg -y -loglevel error ${args} -ac 2 "${OUT}/${name}.wav"`);
  console.log("sfx", name);
}

// Ambient bed: slowly breathing open fifths on A, long enough for the whole film.
const seconds = Number(process.argv[2] ?? 150);
const L = [
  "0.11*sin(2*PI*55*t)*(0.6+0.4*sin(2*PI*0.05*t))",
  "0.07*sin(2*PI*110.2*t)*(0.5+0.5*sin(2*PI*0.031*t))",
  "0.045*sin(2*PI*164.81*t)*(0.5+0.5*sin(2*PI*0.043*t+1))",
  "0.025*sin(2*PI*220.4*t)*(0.5+0.5*sin(2*PI*0.027*t+2))",
  "0.015*sin(2*PI*277.18*t)*(0.5+0.5*sin(2*PI*0.019*t+3))",
].join("+");
const R = L.replace(/110\.2/g, "109.8").replace(/220\.4/g, "219.6");
execSync(
  `ffmpeg -y -loglevel error -f lavfi -i "aevalsrc=exprs='${L}|${R}':s=48000:d=${seconds}" ` +
    `-af "lowpass=f=1800,aecho=0.8:0.8:500|900:0.35|0.25,afade=t=in:d=4,afade=t=out:st=${seconds - 6}:d=6" "public/audio/bed.wav"`,
);
console.log("bed", seconds + "s");
