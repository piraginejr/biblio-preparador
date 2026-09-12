#!/usr/bin/env python3
"""Gera as dez fichas editoriais do lote mai/1953–mai/1954.

Os dados abaixo resultam da leitura dirigida dos textos OCR. O programa
somente aplica o modelo Markdown e se recusa a substituir fichas existentes.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


ISSUES = [
    {
        "year": 1953, "month": "05-06", "date": "Maio–junho de 1953",
        "edition": "Volume 1, número 4", "pages": 16,
        "pdf": "Voice - FGBMFI - 1.4 (May-June 1953).pdf",
        "sha": "2a1781c9288ecc5575a1c6388114fa29163c91f61142afa04d63d5c0aa185535",
        "articles": [
            ("2", "A Message of Light & Truth & Love", "Thomas R. Nickel", "comunicação; testemunho; serviço", "fazer boas obras sem buscar glória pessoal", "Médio-alto"),
            ("3-5", "The Hand of the Lord Is Upon Us!", "Demos Shakarian; Miner Arganbright", "visão; liderança; generosidade; expansão", "discernir uma responsabilidade e sustentá-la com recursos", "Muito alto"),
            ("6-7", "Raised from Deathbed by Power of God!", "Lois Nason; Tommy Hicks", "acidente; oração; cura alegada; testemunho", "buscar ajuda e oração em uma crise extrema", "Alto, com forte cautela médica"),
            ("8-10", "A Pattern for Prosperity", "Lee Braxton", "perseverança; serviço; sucesso; responsabilidade", "trocar passividade por trabalho perseverante e contribuição", "Alto, com cautela teológica"),
            ("11-12", "Plan Global Gospel Broadcast Ship", "Paul B. Fischer", "rádio; direito; inovação; missão global", "colocar competência jurídica e empresarial a serviço da comunicação", "Muito alto"),
            ("15", "Full Gospel Holy Ghost Rallies Break Down Barriers", "R. W. Culpepper", "unidade; cooperação; evangelização", "cooperar além das fronteiras denominacionais", "Alto"),
        ],
        "people": [
            ("Demos Shakarian", "Presidente; articulador da expansão", "visão; liderança; capítulos", "discernir e assumir responsabilidade"),
            ("Miner Arganbright", "Empresário; doador de mil dólares", "generosidade; fé e negócios", "financiar uma obra de forma concreta"),
            ("Lois Nason", "Personagem de testemunho após grave acidente", "sofrimento; oração; cura alegada", "buscar apoio em uma crise"),
            ("Lee Braxton", "Banqueiro, prefeito e vice-presidente", "perseverança; serviço; prosperidade", "servir e perseverar"),
            ("Paul B. Fischer", "Advogado corporativo aposentado", "direito; rádio; missão", "usar competência profissional na missão"),
            ("R. W. Culpepper", "Pastor e dirigente de rallies", "unidade; cooperação", "derrubar barreiras denominacionais"),
        ],
        "topics": ["comunicação cristã", "expansão de capítulos", "fé e negócios", "generosidade", "inovação missionária", "perseverança", "rádio", "sofrimento e cura", "unidade"],
        "decisions": ["apoiar concretamente uma obra", "colocar competência profissional a serviço da missão", "cooperar entre denominações", "perseverar diante de obstáculos", "servir sem buscar reconhecimento"],
        "veins": ["Paul B. Fischer — projeto do navio de radiodifusão", "Demos Shakarian e Miner Arganbright — visão convertida em apoio concreto", "Lee Braxton — perseverança e responsabilidade no sucesso"],
        "cautions": ["Verificar independentemente o prontuário e as alegações de cura de Lois Nason.", "Não transformar o padrão de prosperidade em promessa universal.", "Confirmar a história e a viabilidade do projeto de navio-rádio antes de uso público."],
    },
    {
        "year": 1953, "month": "07-08", "date": "Julho–agosto de 1953",
        "edition": "Volume 1, número 5", "pages": 16,
        "pdf": "Voice - FGBMFI - 1.5 (July-August 1953).pdf",
        "sha": "53c51bb0f7e11ba62728726d7b49bb64a0cecd7991bfc6260f52a32ed50d0dce",
        "articles": [
            ("2", "A Message of Light & Truth & Love", "Thomas R. Nickel", "identidade; doutrina; linguagem religiosa", "examinar com honestidade o significado das palavras usadas", "Médio"),
            ("3, 5", "Our Movement Is Spreading with Power and Speed", "Demos Shakarian", "crescimento; capítulos; comunicação; convenção", "organizar e consolidar uma iniciativa em expansão", "Alto"),
            ("4", "Looking Back and Forward with Encouragement", "Lee Braxton", "memória; unidade; encorajamento", "recordar aprendizados e avançar sem barreiras sociais", "Alto"),
            ("6-9", "A Scientist Discovers God", "N. Jerome Stowell", "ciência; conversão; oração; experimento alegado", "reavaliar convicções diante de uma experiência", "Alto como testemunho, muito baixo como ciência"),
            ("10", "International Convention", "Floyd J. Highfill", "planejamento; encontro; mobilização", "participar e organizar um encontro coletivo", "Médio-alto"),
            ("12", "Contrasting Temporary with Permanent Values", "Miner Arganbright", "bens; ruínas; valores eternos", "subordinar patrimônio a valores permanentes", "Alto"),
            ("15", "Esther Lei Johnson and Mitsuo Fuchida", "Esther Lei Johnson; Mitsuo Fuchida", "Pearl Harbor; conversão; reconciliação", "romper ciclos de hostilidade e testemunhar mudança", "Muito alto, com verificação histórica"),
        ],
        "people": [
            ("Demos Shakarian", "Presidente e organizador", "crescimento; capítulos; convenção", "consolidar uma obra em expansão"),
            ("Lee Braxton", "Vice-presidente e autor", "unidade; memória; encorajamento", "aprender com a caminhada"),
            ("N. Jerome Stowell", "Apresentado como cientista convertido", "ciência; conversão; oração", "reavaliar convicções"),
            ("Floyd J. Highfill", "Secretário executivo", "planejamento; convenção", "organizar coletivamente"),
            ("Miner Arganbright", "Empresário e vice-presidente", "valores; patrimônio; eternidade", "reordenar prioridades"),
            ("Esther Lei Johnson e Mitsuo Fuchida", "Personagens ligados a Pearl Harbor", "guerra; conversão; reconciliação", "superar hostilidade"),
        ],
        "topics": ["crescimento institucional", "ciência e fé", "convenção", "reconciliação", "unidade", "valores permanentes", "Pearl Harbor", "comunicação"],
        "decisions": ["consolidar uma iniciativa em crescimento", "reavaliar convicções", "reordenar prioridades", "romper ciclos de hostilidade", "participar de uma construção coletiva"],
        "veins": ["Esther Lei Johnson e Mitsuo Fuchida — memória de guerra e reconciliação", "Miner Arganbright — valores temporários e permanentes", "Lee Braxton — olhar para trás e avançar com encorajamento"],
        "cautions": ["As afirmações experimentais atribuídas a Stowell não constituem evidência científica e exigem checagem especializada.", "Confirmar os dados biográficos de Esther Johnson e Mitsuo Fuchida.", "Tratar números de crescimento como relato institucional."],
    },
    {
        "year": 1953, "month": "09", "date": "Setembro de 1953",
        "edition": "Volume 1, número 6", "pages": 16,
        "pdf": "Voice - FGBMFI - 1.6 (September 1953).pdf",
        "sha": "5dbec2ddab46d604100398cba218f97ee975861146391bfd5aec4188b907be2c",
        "articles": [
            ("2", "A Message of Light & Truth & Love", "Thomas R. Nickel", "poder; humildade; cruz", "não transformar experiências em motivo de orgulho", "Alto"),
            ("3-5", "International and Chapters Busy on All Fronts", "Demos Shakarian", "Tacoma; capítulos; unidade; convenção", "cooperar, organizar e fortalecer comunidades locais", "Alto"),
            ("6-7, 10", "A Divine Warning to Mankind", "A. C. Valdez Jr.", "profecia; catástrofes; arrependimento; medo", "examinar a vida e buscar reconciliação", "Médio, com forte cautela profética"),
            ("8-9", "First Annual Convention", "Liderança da FGBMFI", "convenção; logística; mobilização", "planejar e participar de uma ação conjunta", "Médio-alto"),
            ("12-14", "Mighty Is the Power of God", "N. Jerome Stowell; A. C. Valdez Sr.", "energia nuclear; Bíblia; proteção sobrenatural", "buscar confiança em meio ao medo", "Baixo como ciência; cautela muito alta"),
        ],
        "people": [
            ("Demos Shakarian", "Presidente e articulador de capítulos", "unidade; expansão; convenção", "organizar sem perder o foco local"),
            ("A. C. Valdez Jr.", "Evangelista; autor de advertência profética", "catástrofe; arrependimento", "examinar a própria vida"),
            ("N. Jerome Stowell", "Apresentado como cientista nuclear", "ciência; Bíblia; proteção", "buscar confiança"),
            ("Howard Toy", "Dirigente do capítulo de Tacoma", "liderança local; cooperação", "assumir responsabilidade comunitária"),
            ("Thomas R. Nickel", "Editor", "humildade; comunicação", "evitar orgulho espiritual"),
        ],
        "topics": ["catástrofes", "ciência e fé", "convenção", "expansão de capítulos", "humildade", "medo", "profecia", "Tacoma", "unidade"],
        "decisions": ["evitar orgulho espiritual", "examinar a própria vida", "fortalecer comunidades locais", "planejar uma ação conjunta", "responder ao medo sem sensacionalismo"],
        "veins": ["Thomas Nickel — poder sem orgulho", "Demos Shakarian — expansão em várias frentes", "Advertência profética — potencial apenas com contextualização crítica"],
        "cautions": ["Não apresentar previsões de catástrofe como fatos ou profecias confirmadas.", "As explicações nucleares e físicas atribuídas a Stowell são cientificamente frágeis.", "Evitar uso pastoral que intensifique medo ou prometa imunidade física."],
    },
    {
        "year": 1953, "month": "10", "date": "Outubro de 1953",
        "edition": "Volume 1, número 7", "pages": 15,
        "pdf": "Voice - FGBMFI - 1.7 (October 1953).pdf",
        "sha": "a5d6db6c30b48b8084de79b6381e10d9a2e384f395c992069134158f7061c68b",
        "articles": [
            ("3-4", "The Amazing Shakarian Story — Part One", "Thomas R. Nickel; família Shakarian", "Armênia; migração; memória familiar; fé", "preservar memória e responder com prudência a tempos de crise", "Muito alto, com verificação histórica"),
            ("5-6", "Our Organization from an Attorney's Standpoint", "Paul B. Fischer", "governança; igreja local; unidade; direito", "criar estruturas que sirvam sem duplicar a igreja", "Muito alto"),
            ("7", "Local Chapters Sovereign", "Liderança da FGBMFI", "autonomia; padrões comuns; responsabilidade", "equilibrar autonomia local e identidade compartilhada", "Alto"),
            ("9-10", "The Word of God Is Scientifically True", "N. Jerome Stowell", "criação; fósseis; ciência; Bíblia", "examinar alegações e fundamentos", "Baixo como ciência; relevante para história das ideias"),
            ("11-13", "Editor's Mail — Africa and Israel", "Missionários e leitores", "rádio; Bíblias; África; Israel; apoio", "responder a necessidades concretas de parceiros distantes", "Alto, com contextualização"),
        ],
        "people": [
            ("Família Shakarian", "Família armênia migrante", "memória; migração; fé", "preservar memória familiar"),
            ("Paul B. Fischer", "Advogado corporativo", "governança; unidade; igreja local", "desenhar estrutura responsável"),
            ("N. Jerome Stowell", "Apresentado como cientista", "criação; Bíblia; ciência", "examinar alegações"),
            ("Thomas R. Nickel", "Editor e narrador", "biografia; comunicação", "registrar a história"),
            ("Missionários na África e em Israel", "Correspondentes da revista", "rádio; literatura; apoio", "atender necessidades concretas"),
        ],
        "topics": ["Armênia", "autonomia local", "ciência e fé", "governança", "igreja local", "migração", "missão", "memória familiar", "unidade"],
        "decisions": ["equilibrar autonomia e padrões comuns", "estruturar uma organização para servir", "preservar memória familiar", "responder a necessidades missionárias", "submeter alegações científicas à verificação"],
        "veins": ["Paul Fischer — organização que fortalece igrejas sem duplicá-las", "Família Shakarian — migração, memória e fé", "Autonomia dos capítulos — unidade sem centralização excessiva"],
        "cautions": ["Verificar a cronologia e as profecias ligadas à migração armênia.", "Não usar Stowell como fonte científica sobre idade da Terra ou fósseis.", "Contextualizar linguagem missionária e política sobre África, Israel e comunismo."],
    },
    {
        "year": 1953, "month": "11", "date": "Novembro de 1953",
        "edition": "Volume 1, número 8", "pages": 15,
        "pdf": "Voice - FGBMFI - 1.8 (November 1953).pdf",
        "sha": "05d82b50456c090dabbdd13e3e6b80ff3538e368ac831e309ccb66fad096f36c",
        "articles": [
            ("3-5", "I Found the Source of Truth — Part One", "Henry Krause", "invenção; indústria; desilusão; busca espiritual", "não apoiar a verdade apenas em prestígio humano", "Muito alto"),
            ("6-7", "The Amazing Shakarian Story — Part Two", "Thomas R. Nickel; Isaac Shakarian", "imigração; família; trabalho; crescimento empresarial", "integrar fé, família e trabalho sem confundi-los", "Alto"),
            ("8-13", "First Annual Convention Report", "Thomas R. Nickel e participantes", "convenção; liderança; testemunhos; organização", "avaliar resultados, repartir funções e consolidar a obra", "Alto"),
            ("14", "What the Convention Meant to Me", "Demos Shakarian", "gratidão; cooperação; liderança", "reconhecer contribuições e manter o senso de missão", "Muito alto"),
        ],
        "people": [
            ("Henry Krause", "Fabricante de arados e diretor", "inovação; indústria; verdade", "não depositar confiança final no prestígio"),
            ("Isaac Shakarian", "Patriarca da família e empresário", "família; trabalho; imigração", "integrar fé e trabalho"),
            ("Demos Shakarian", "Presidente", "convenção; gratidão; liderança", "reconhecer colaboradores"),
            ("Thomas R. Nickel", "Editor e relator da convenção", "memória institucional; comunicação", "registrar e avaliar resultados"),
            ("Harold G. Kabisch", "Secretário-tesoureiro eleito", "administração; transição", "assumir responsabilidade organizacional"),
        ],
        "topics": ["convenção", "empresa familiar", "gratidão", "imigração", "indústria", "liderança", "memória institucional", "transição", "verdade"],
        "decisions": ["avaliar resultados", "integrar fé, família e trabalho", "não apoiar a verdade em prestígio humano", "reconhecer colaboradores", "repartir funções"],
        "veins": ["Henry Krause — sucesso industrial e busca pela verdade", "Relato da primeira convenção — organização e transição", "Demos Shakarian — gratidão a uma rede de colaboradores"],
        "cautions": ["Tratar números, curas e conversões da convenção como relatos institucionais.", "Evitar associar crescimento empresarial a aprovação divina automática.", "Confirmar dados empresariais e biográficos de Henry Krause."],
    },
    {
        "year": 1953, "month": "12", "date": "Dezembro de 1953",
        "edition": "Volume 1, número 9", "pages": 16,
        "pdf": "Voice - FGBMFI - 1.9 (December 1953).pdf",
        "sha": "bb1a65d7aef3321d92e5412dbf33c440068cdc8247561c1142fca7606dffbbbf",
        "articles": [
            ("3-4", "The House with the Golden Windows — Part One", "Lee Braxton", "perspectiva; contentamento; vocação; recursos presentes", "reconhecer o valor do que já está nas mãos", "Muito alto"),
            ("5-6", "I Found the Source of Truth — Part Two", "Henry Krause", "discernimento; generosidade; convicção", "buscar convicção própria e usar recursos para servir", "Alto"),
            ("7", "We Know When We Feel the Pull", "A. O. Barnes", "fé; invisível; perseverança", "perseverar mesmo sem ver todos os resultados", "Alto"),
            ("8-10", "The Amazing Shakarian Story — Part Three", "Demos Shakarian; Thomas R. Nickel", "vocação; campanhas; família; cura alegada", "transformar recursos em serviço e perseverar no chamado", "Alto, com cautela médica"),
            ("11", "The True Christmas Story", "Percy D. Fraser", "Natal; fidelidade; esperança", "acolher Cristo e permanecer fiel sob incompreensão", "Alto"),
        ],
        "people": [
            ("Lee Braxton", "Banqueiro, prefeito e autor", "perspectiva; contentamento; vocação", "valorizar o que já possui"),
            ("Henry Krause", "Industrial e diretor", "verdade; generosidade", "servir com recursos"),
            ("A. O. Barnes", "Farmacêutico industrial", "fé; perseverança", "continuar mesmo sem ver"),
            ("Demos Shakarian", "Empresário e patrocinador de campanhas", "vocação; serviço; família", "usar recursos na missão"),
            ("Percy D. Fraser", "Diretor do grupo de oração", "Natal; esperança", "permanecer fiel"),
        ],
        "topics": ["contentamento", "família", "generosidade", "Natal", "perspectiva", "perseverança", "recursos", "verdade", "vocação"],
        "decisions": ["buscar convicção própria", "perseverar sem ver todos os resultados", "reconhecer o valor do que já se tem", "usar recursos para servir", "viver o Natal com fidelidade"],
        "veins": ["Lee Braxton — a casa com janelas douradas estava no ponto de partida", "A. O. Barnes — sentir o puxão mesmo sem ver a pipa", "Henry Krause — convicção própria e generosidade"],
        "cautions": ["Verificar os relatos de acidentes e curas na história Shakarian.", "Distinguir testemunho biográfico de comprovação externa.", "Evitar romantizar sofrimento ou pobreza por meio da metáfora das janelas douradas."],
    },
    {
        "year": 1954, "month": "01", "date": "Janeiro de 1954",
        "edition": "Volume 1, número 10", "pages": 16,
        "pdf": "Voice - FGBMFI - 1.10 (January 1954).pdf",
        "sha": "20cf628ca28c117f33e43e7d3da8c8b338867c0f426c33150b5ea6420ee0c0ae",
        "articles": [
            ("3", "Catholic Helps Protestants — Part One", "Giacomo Rosapepe; Alfred Perna", "Itália; liberdade religiosa; direito; cooperação", "usar conhecimento jurídico para defender uma minoria", "Muito alto, com contextualização"),
            ("4-7", "Our Organization Is Moving Ahead", "Demos Shakarian", "viagem; capítulos; rádio; expansão", "visitar, ouvir e consolidar núcleos locais", "Alto"),
            ("8-10", "Chapter Reports", "Lideranças de Reading, Springfield e Chicago", "unidade; transparência; conversão; organização", "abrir a vida, cooperar e assumir funções locais", "Alto"),
            ("11-12", "The Amazing Shakarian Story — Part Four", "Thomas R. Nickel; Charles S. Price", "mentoria; campanhas; cura alegada; legado", "aprender com mentores e preparar continuidade", "Alto, com cautela histórica"),
            ("14", "The House with the Golden Windows — Part Two", "Lee Braxton", "contentamento; trabalho; aposentadoria; propósito", "não confundir mudança externa com solução interior", "Muito alto"),
            ("15", "Pittsburgh Chapter Being Blessed", "Daniel R. Ofchinick", "capítulo; rádio; dons; comunhão", "fortalecer uma comunidade local", "Médio-alto"),
        ],
        "people": [
            ("Giacomo Rosapepe", "Advogado católico italiano", "direito; liberdade religiosa", "defender uma minoria"),
            ("Alfred Perna", "Intérprete e articulador", "tradução; cooperação", "construir pontes"),
            ("Demos Shakarian", "Presidente em viagem de expansão", "capítulos; rádio; liderança", "consolidar núcleos"),
            ("Charles S. Price", "Evangelista e mentor", "legado; campanhas; cura alegada", "preparar continuidade"),
            ("Lee Braxton", "Empresário e autor", "contentamento; trabalho; propósito", "não fugir de problemas por mudança externa"),
            ("Daniel R. Ofchinick", "Autor ligado ao capítulo de Pittsburgh", "comunhão; rádio", "fortalecer a comunidade"),
        ],
        "topics": ["capítulos", "contentamento", "cooperação", "direito", "expansão", "liberdade religiosa", "mentoria", "rádio", "trabalho"],
        "decisions": ["construir pontes", "defender uma minoria religiosa", "fortalecer uma comunidade local", "não confundir mudança externa com transformação", "preparar continuidade"],
        "veins": ["Giacomo Rosapepe — competência jurídica em defesa de protestantes", "Lee Braxton — propósito antes de mudança externa", "Expansão por visitas — ouvir e consolidar comunidades locais"],
        "cautions": ["Verificar o processo jurídico italiano e evitar linguagem anticatólica.", "Tratar curas e números de campanhas como alegações.", "Contextualizar afirmações de prosperidade, saúde e bênção nos relatos dos capítulos."],
    },
    {
        "year": 1954, "month": "02-03", "date": "Fevereiro–março de 1954",
        "edition": "Volume 2, número 1", "pages": 16,
        "pdf": "Voice - FGBMFI - 2.1 (February-March 1954).pdf",
        "sha": "38ad8744d5b4dcc81479490bfce5b992fdc1eda3279eeef2fb3c9823f6352dd0",
        "articles": [
            ("3", "Roque Gallardo's Unusual Conversion", "Roque Gallardo; Nyles G. Huffman", "México; conversão; tradução; missão indígena", "atravessar barreiras linguísticas e apoiar lideranças locais", "Alto, com contextualização cultural"),
            ("4", "The Amazing Shakarian Story — Part Five", "Thomas R. Nickel; Demos Shakarian", "ação unida; fundação; financiamento; visão", "oferecer habilidades e recursos para uma visão comum", "Muito alto"),
            ("5", "The House with the Golden Windows — Part Three", "Lee Braxton", "humildade; propósito; caráter; sucesso", "retirar o supérfluo e cultivar humildade", "Muito alto"),
            ("6-7, 10-11", "Two Chapters Organized in Florida", "Demos Shakarian; H. C. M. Foster", "capítulos; empresários; unidade; cura alegada", "organizar comunidades e colocar negócios a serviço", "Alto, com cautela médica"),
            ("8-9, 13", "The Wallace Nickel Miracle", "Thomas R. Nickel; Wallace Nickel", "acidente; responsabilidade; oração; recuperação", "buscar socorro, assumir responsabilidade e sustentar esperança", "Alto, com forte cautela médica"),
            ("14-15", "Dallas Chapter and Convention Planning", "Lideranças locais", "organização; clima adverso; planejamento", "perseverar e cuidar dos detalhes", "Alto"),
        ],
        "people": [
            ("Roque Gallardo", "Indígena asteca apresentado como evangelista", "conversão; missão; México", "servir em seu contexto"),
            ("Nyles G. Huffman", "Missionário e intérprete", "tradução; apoio local", "atravessar barreiras linguísticas"),
            ("Demos Shakarian", "Fundador e organizador", "visão; capítulos; ação unida", "mobilizar recursos"),
            ("Lee Braxton", "Empresário e autor", "humildade; propósito; sucesso", "cultivar caráter"),
            ("Thomas e Wallace Nickel", "Pai e filho em relato de acidente", "responsabilidade; oração; recuperação", "buscar socorro e sustentar esperança"),
            ("H. C. M. Foster", "Empresário do setor leiteiro", "negócios; cura alegada; capítulo", "colocar influência a serviço"),
        ],
        "topics": ["acidente", "ação unida", "capítulos", "humildade", "México", "missão indígena", "planejamento", "tradução", "vocação"],
        "decisions": ["atravessar barreiras linguísticas", "cuidar dos detalhes", "cultivar humildade", "oferecer habilidades a uma visão comum", "organizar uma comunidade local"],
        "veins": ["Fundação da FGBMFI — habilidades e recursos convergindo", "Lee Braxton — sucesso moldado por humildade", "Roque Gallardo — tradução e liderança contextual"],
        "cautions": ["Evitar linguagem paternalista ao tratar Roque Gallardo e povos indígenas.", "O relato de Wallace envolve alta velocidade e alegações médicas; não omitir a dimensão de responsabilidade.", "Verificar curas e dados empresariais de H. C. M. Foster."],
    },
    {
        "year": 1954, "month": "04", "date": "Abril de 1954",
        "edition": "Volume 2, número 2", "pages": 16,
        "pdf": "Voice - FGBMFI - 2.2 (April 1954).pdf",
        "sha": "a8eccdf8d86edd3363bc4c1ed68618316a41e5cb87becdb1c7fb375db2988783",
        "articles": [
            ("3", "Plans Being Made for Convention", "Liderança da FGBMFI", "Washington; planejamento; governo; convenção", "planejar com antecedência sem prometer resultados", "Alto"),
            ("4-5, 14", "I Praise God for This Day!", "Howard C. Toy; família Garbett", "surdez; oração; cura alegada; inclusão", "acolher uma família e agir com compaixão", "Alto, com cautela médica e de deficiência"),
            ("6-7", "The House with the Golden Windows — Part Four", "Lee Braxton", "propósito; trabalho; resposta; serviço", "responder criativamente às circunstâncias", "Muito alto"),
            ("8-9", "Denver Chapter Sponsors Meeting", "C. C. Ford; Judge Cook; D. H. Sala", "organização; finanças; ação; campanha", "passar da organização à ação responsável", "Alto"),
            ("10-11", "The Amazing Shakarian Story — Part Six", "Demos Shakarian; Richard Shakarian", "negócios; família; disciplina espiritual", "proteger a vida espiritual em meio ao crescimento profissional", "Muito alto"),
            ("15", "Regarding Our Fellowship Treasury", "Demos Shakarian", "prestação de contas; custos; contribuição", "sustentar a missão com regularidade e transparência", "Muito alto"),
        ],
        "people": [
            ("Howard C. Toy", "Diretor e participante do relato Garbett", "compaixão; oração; inclusão", "acolher e servir uma família"),
            ("Família Garbett", "Família surda apresentada em testemunho", "deficiência; acolhimento; cura alegada", "buscar pertencimento"),
            ("Lee Braxton", "Empresário e autor", "propósito; resposta; serviço", "responder criativamente"),
            ("Demos Shakarian", "Presidente e empresário", "negócios; tesouraria; disciplina", "praticar transparência"),
            ("Richard Shakarian", "Jovem ligado à família e ao ministério", "juventude; vocação; disciplina", "cultivar vocação cedo"),
            ("C. C. Ford e D. H. Sala", "Organizadores do capítulo de Denver", "ação; finanças; liderança", "transformar organização em serviço"),
        ],
        "topics": ["deficiência", "finanças", "inclusão", "negócios", "planejamento", "prestação de contas", "propósito", "trabalho", "juventude"],
        "decisions": ["agir com compaixão", "passar da organização à ação", "planejar sem prometer", "proteger a vida espiritual", "responder criativamente às circunstâncias", "sustentar com transparência"],
        "veins": ["Tesouraria — missão exige contribuição regular e prestação de contas", "Lee Braxton — responder em vez de apenas reagir", "Demos Shakarian — crescimento profissional e disciplina espiritual"],
        "cautions": ["Não tratar surdez como falha espiritual nem usar a família Garbett sem confirmar o relato e empregar linguagem respeitosa sobre deficiência.", "Confirmar qualquer alegação sobre participação de Eisenhower.", "Avaliar criticamente financiamento de campanhas e linguagem de prosperidade."],
    },
    {
        "year": 1954, "month": "05", "date": "Maio de 1954",
        "edition": "Volume 2, número 3", "pages": 16,
        "pdf": "Voice - FGBMFI - 2.3 (May 1954).pdf",
        "sha": "b255413bc50012887f61b3d53f032b3be0376086fbdffbf7caf0e9c5af36d5b1",
        "articles": [
            ("3, 6, 15", "Our Choice: Revival or Ruin!", "Douglas G. Scott", "Extremo Oriente; Guerra da Coreia; capelania; moral", "servir pessoas em ambiente de guerra e reconstrução", "Alto, com contextualização histórica"),
            ("4-5", "Argentina Is Opened to the Full Gospel!", "Tommy Hicks; Louie Stokes; Angelo Arbizu", "Argentina; campanha; mídia; cura alegada", "construir parcerias locais e comunicar amplamente", "Alto, com forte verificação"),
            ("7, 14-15", "Catholic Helps Protestants — Part Two", "Giacomo Rosapepe; Alfred Perna", "Itália; direito; liberdade religiosa; minoria", "defender liberdade de culto por meios jurídicos", "Muito alto"),
            ("8-11", "Attend Our Fellowship Convention", "Demos Shakarian", "consagração; serviço; convenção; unidade", "oferecer a própria vida, não apenas contribuição material", "Muito alto"),
            ("12-13", "Editor's Mail — Global Missions", "Correspondentes em Israel, Índia, Chile e EUA", "rede global; literatura; aldeias; Chinatown", "responder a oportunidades concretas e apoiar lideranças locais", "Alto"),
        ],
        "people": [
            ("Douglas G. Scott", "Ministro e participante de missão da Força Aérea", "Coreia; Japão; capelania; guerra", "servir em contexto de reconstrução"),
            ("Tommy Hicks", "Evangelista em campanha na Argentina", "campanha; mídia; missão", "trabalhar com parceiros locais"),
            ("Louie Stokes e Angelo Arbizu", "Missionários e articuladores sul-americanos", "Argentina; Chile; tradução cultural", "abrir caminhos locais"),
            ("Giacomo Rosapepe", "Advogado italiano", "direito; liberdade de culto", "defender comunidades vulneráveis"),
            ("Demos Shakarian", "Presidente", "consagração; serviço; unidade", "oferecer a própria vida"),
            ("Alfred Perna", "Intérprete", "mediação; cooperação", "construir pontes"),
        ],
        "topics": ["Argentina", "capelania", "consagração", "Coreia", "direito", "Extremo Oriente", "Itália", "liberdade religiosa", "missão global"],
        "decisions": ["apoiar lideranças locais", "construir parcerias transculturais", "defender liberdade religiosa", "oferecer a própria vida ao serviço", "servir em ambiente de reconstrução"],
        "veins": ["Giacomo Rosapepe — defesa jurídica de uma minoria religiosa", "Douglas Scott — capelania em cenário de guerra e reconstrução", "Demos Shakarian — além do dinheiro, entrega pessoal"],
        "cautions": ["Verificar números, curas, permissões políticas e participação de autoridades argentinas.", "Contextualizar Guerra da Coreia, Japão e linguagem sobre povos asiáticos.", "Evitar antagonismo católico-protestante e confirmar o processo jurídico italiano."],
    },
]


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {item};" for item in items[:-1]) + (
        f"\n- {items[-1]}." if items else ""
    )


def render(issue: dict) -> str:
    articles = "\n".join(
        f"| {pages} | {title} | {person} | {topics} | {decision} | {potential} |"
        for pages, title, person, topics, decision, potential in issue["articles"]
    )
    people = "\n".join(
        f"| {name} | {context} | {topics} | {decision} |"
        for name, context, topics, decision in issue["people"]
    )
    veins = "\n".join(
        f"{number}. **{item}**" for number, item in enumerate(issue["veins"], 1)
    )
    cautions = "\n".join(f"- {item}" for item in issue["cautions"])
    return f"""# FGMBV - {issue['edition']} - {issue['date']}

## Identificação

| Campo | Registro |
|---|---|
| Coleção | Full Gospel Business Men's Voice Magazine |
| Edição | {issue['edition']} |
| Data | {issue['date']} |
| Editor | Thomas R. Nickel |
| Extensão | {issue['pages']} páginas |
| Fonte | ORU Digital Showcase; exemplar preservado localmente |
| PDF local | `../../01-EDICOES-PDF/{issue['year']}/{issue['pdf']}` |
| Texto pesquisável | `{Path(issue['pdf']).stem}.txt` |
| Estado | Mineração preliminar concluída |
| Integridade | PDF validado; OCR presente; sem criptografia |
| SHA-256 | `{issue['sha']}` |

Esta ficha registra potencialidades. Ela não transforma as matérias em
ilustrações prontas e não valida de modo independente as alegações históricas,
numéricas, médicas, científicas ou sobrenaturais presentes nos testemunhos.

## Matérias e potencialidades

| Páginas | Matéria | Autor ou personagem central | Assuntos básicos | Decisões potencialmente induzidas | Potencial |
|---:|---|---|---|---|---|
{articles}

## Personagens principais

| Personagem | Categoria ou contexto informado na edição | Assuntos associados | Decisões potenciais |
|---|---|---|---|
{people}

## Índice de assuntos desta edição

{bullets(issue['topics'])}

## Índice de decisões potenciais desta edição

{bullets(issue['decisions'])}

## Veios de maior potencial

{veins}

## Cuidados para pesquisa dirigida

{cautions}
- Confirmar nomes e dados biográficos afetados por ruído de OCR.
- Respeitar a restrição da ORU e da FGBMFI contra redistribuição dos PDFs.
"""


def main() -> int:
    created = 0
    for issue in ISSUES:
        folder = ROOT / "02-MINERACAO" / str(issue["year"])
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (
            f"FGMBV-{issue['year']}-{issue['month']}-"
            f"v{issue['edition'].split()[1].rstrip(',')}-"
            f"n{issue['edition'].split()[-1]}.md"
        )
        if target.exists():
            print(f"PRESERVADA: {target.relative_to(ROOT)}")
            continue
        temporary = target.with_suffix(".md.part")
        temporary.write_text(render(issue), encoding="utf-8")
        temporary.replace(target)
        created += 1
        print(f"CRIADA: {target.relative_to(ROOT)}")
    print(f"Novas fichas: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
