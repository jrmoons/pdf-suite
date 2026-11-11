cd "/c/Users/JérémyMoons/.local/bin/pdf-suite"
S="C:/Users/JRMYMO~1/AppData/Local/Temp/claude/a7d3f2d3b4a5bed3/8c969d58-1571-4c64-baec-490d4b906bc5/scratchpad"
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe $S/bench.py "10*.pdf" > $S/b_a2.txt 2>/dev/null
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe $S/bench.py "a1_*.pdf" > $S/b_a1.txt 2>/dev/null
for k in a2 a1; do awk -F'\t' -v k=$k 'NF>8 {n++; if($5!=""){r=($5-$4)/$4; if(r<0)r=-r; if(r<=0.01)a++; if(r<=0.02)b++; if(r<=0.05)c++}} END{print k": "n" pièces, 1%:"a", 2%:"b", 5%:"c}' $S/b_$k.txt; done
