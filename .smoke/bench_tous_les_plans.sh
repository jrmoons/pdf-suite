cd "/c/Users/JérémyMoons/.local/bin/pdf-suite"
S="$(cygpath -u "${BENCH_OUT:-$TEMP/claude_bench}")"; mkdir -p "$S"
for k in "a2:10*.pdf" "a1:a1_*.pdf" "dav:dav_*.pdf" "con:con_*.pdf" "sch:sch_*.pdf"; do
  n=${k%%:*}; g=${k#*:}
  QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe .smoke/bench_pieces_arlon.py "$g" > $S/b_$n.txt 2>/dev/null
  awk -F'\t' -v k=$n 'NF>8 {n++; if($5!=""){r=($5-$4)/$4; if(r<0)r=-r; if(r<=0.01)a++; if(r<=0.02)b++; if(r<=0.05)c++}} END{printf "%-4s %3d pièces | 2%%: %3d | 5%%: %3d\n", k, n, b, c}' $S/b_$n.txt
done
cat $S/b_*.txt | awk -F'\t' 'NF>8 {n++; if($5!=""){r=($5-$4)/$4; if(r<0)r=-r; if(r<=0.02)b++; if(r<=0.05)c++}} END{printf "TOTAL %d pièces | justes à 2%%: %d (%.0f%%) | à 5%%: %d (%.0f%%)\n", n, b, 100*b/n, c, 100*c/n}'
