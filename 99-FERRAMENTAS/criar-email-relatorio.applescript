on run argumentos
    if (count of argumentos) is not 6 then error "Argumentos insuficientes para criar o e-mail."
    set enderecoDestino to item 1 of argumentos
    set enderecoRemetente to item 2 of argumentos
    set assuntoMensagem to item 3 of argumentos
    set corpoMensagem to item 4 of argumentos
    set caminhoHTML to item 5 of argumentos
    set caminhoCSV to item 6 of argumentos

    tell application "Mail"
        set novaMensagem to make new outgoing message with properties {subject:assuntoMensagem, content:(corpoMensagem & return & return), visible:true}
        tell novaMensagem
            set sender to enderecoRemetente
            make new to recipient at end of to recipients with properties {address:enderecoDestino}
            tell content
                make new attachment with properties {file name:(POSIX file caminhoHTML)} at after last paragraph
                make new attachment with properties {file name:(POSIX file caminhoCSV)} at after last paragraph
            end tell
            save
        end tell
        activate
    end tell
    return "RASCUNHO_CRIADO"
end run
