import datetime

def slot_to_str(s: int) -> str:
    h = s // 2
    m = (s % 2) * 30
    return f"{h:02d}:{m:02d}"

def encontrar_horarios_comuns(disponibilidades: list[dict], limite=3) -> list[str]:
    """
    Recebe lista de dicts. Os slots agora são "YYYY-MM-DD,S".
    Retorna lista com até 3 strings de horários em comum.
    """
    if not disponibilidades:
        return []

    sets = [set(d["slots"]) for d in disponibilidades]
    comum = sets[0]
    for s in sets[1:]:
        comum &= s

    if not comum:
        return []

    # Agrupa os slots comuns por dia (data ISO)
    dias_encontrados = {}
    for slot_str in comum:
        try:
            dia_str, slot_idx = slot_str.split(",")
            slot_idx = int(slot_idx)
            if dia_str not in dias_encontrados:
                dias_encontrados[dia_str] = []
            dias_encontrados[dia_str].append(slot_idx)
        except ValueError:
            pass

    dias_ordenados = sorted(dias_encontrados.keys())
    opcoes_slots = []
    
    # 1. Estratégia principal: pegar o horário mais cedo de dias diferentes
    for dia in dias_ordenados:
        mais_cedo = min(dias_encontrados[dia])
        opcoes_slots.append((dia, mais_cedo))
        if len(opcoes_slots) == limite:
            break
            
    # 2. Se não bateu o limite preenche os vagos com ordem cronológica
    if len(opcoes_slots) < limite:
        todos_ordenados = []
        for dia in dias_ordenados:
            for s in sorted(dias_encontrados[dia]):
                todos_ordenados.append((dia, s))
                
        for slot in todos_ordenados:
            if slot not in opcoes_slots:
                opcoes_slots.append(slot)
                if len(opcoes_slots) == limite:
                    break
                    
    opcoes_slots.sort()
    
    opcoes = []
    nomes_dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
    
    for dia_str, slot_idx in opcoes_slots:
        try:
            d_obj = datetime.datetime.strptime(dia_str, "%Y-%m-%d")
            nome_dia = nomes_dias[d_obj.weekday()].capitalize().replace("-feira", "")
            opcoes.append(f"{nome_dia} {d_obj.day:02d}/{d_obj.month:02d} às {slot_to_str(slot_idx)}")
        except Exception:
            opcoes.append(f"Data Indefinida às {slot_to_str(slot_idx)}")

    return opcoes

def formatar_disponibilidades(disponibilidades: list[dict], guild_members: dict) -> str:
    if not disponibilidades:
        return "Ninguém respondeu ainda."
        
    res = []
    nomes_dias = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    for disp in disponibilidades:
        pid = disp["discord_id"]
        nome = guild_members.get(pid, pid)
        
        mapa = {}
        for slot_str in sorted(disp["slots"]):
            try:
                dia_str, s_str = slot_str.split(",")
                s = int(s_str)
                if dia_str not in mapa: 
                    mapa[dia_str] = []
                mapa[dia_str].append(s)
            except ValueError:
                continue
            
        partes = []
        for dia_str in sorted(mapa.keys()):
            try:
                d_obj = datetime.datetime.strptime(dia_str, "%Y-%m-%d")
                nome_dia = f"{nomes_dias[d_obj.weekday()]} {d_obj.day:02d}/{d_obj.month:02d}"
            except:
                nome_dia = "Dia"
                
            slots = sorted(mapa[dia_str])
            ranges = []
            inicio = slots[0]
            fim = slots[0]
            for s in slots[1:]:
                if s == fim + 1:
                    fim = s
                else:
                    ranges.append((inicio, fim))
                    inicio = s
                    fim = s
            ranges.append((inicio, fim))
            
            rg_strs = []
            for i, f in ranges:
                # Mostrar o limite de fechamento (+30min) pro usuário bater olho
                rg_strs.append(f"{slot_to_str(i)}–{slot_to_str(f+1)}")
                
            partes.append(f"**{nome_dia}**: {', '.join(rg_strs)}")
            
        txt = " | ".join(partes) if partes else "Sem horários"
        res.append(f"• **{nome}**: {txt}")
        
    return "\\n".join(res)
