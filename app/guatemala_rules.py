# Lógica de impuestos y laborales de Guatemala
IGSS_LABORAL = 0.0483  # 4.83%
BONO_INCENTIVO = 250.00  # Q250.00 al mes (Decreto 37-2001)
DEDUCCION_PERSONAL_ISR = 48000.00  # Deducción fija anual exenta (Decreto 10-2012)

def calcular_planilla_empleado(sueldo_base, dias_trabajados, es_dolares=False, tipo_cambio=7.80, aplica_isr=True):
    """
    Calcula los datos de planilla ajustados a la ley de Guatemala.
    Soporta cobro en Quetzales (GTQ) o Dólares (USD) e incluye retención real de ISR.
    """
    if es_dolares:
        sueldo_gtq = sueldo_base * tipo_cambio
    else:
        sueldo_gtq = sueldo_base

    sueldo_devengado = (sueldo_gtq / 30) * dias_trabajados
    
    # 1. IGSS Laboral (4.83% sobre sueldo ordinario)
    igss = round(sueldo_devengado * IGSS_LABORAL, 2)
    
    # 2. Bonificación Incentivo (Exenta de IGSS e ISR)
    bono = round((BONO_INCENTIVO / 30) * dias_trabajados, 2)
    
    # 3. Retención de ISR Proyectada (Ley de Actualización Tributaria, Decreto 10-2012)
    isr_mensual = 0.0
    if aplica_isr:
        proyeccion_anual_renta = sueldo_devengado * 12
        proyeccion_anual_igss = igss * 12
        renta_imponible_anual = proyeccion_anual_renta - DEDUCCION_PERSONAL_ISR - proyeccion_anual_igss
        
        if renta_imponible_anual > 0:
            if renta_imponible_anual <= 300000.00:
                isr_anual = renta_imponible_anual * 0.05
            else:
                isr_anual = 15000.00 + ((renta_imponible_anual - 300000.00) * 0.07)
            isr_mensual = round(isr_anual / 12, 2)

    # 4. Provisión mensual de Indemnización (Factor 14/12)
    indemnizacion_mensual = round((sueldo_devengado * (14 / 12)) / 12, 2)
    
    # 5. Sueldo Líquido a recibir
    total_liquido_gtq = round(sueldo_devengado + bono - igss - isr_mensual, 2)
    
    return {
        'sueldo_gtq': round(sueldo_devengado, 2),
        'igss': igss,
        'bono_incentivo': bono,
        'isr': isr_mensual,
        'indemnizacion_mensual': indemnizacion_mensual,
        'total_liquido_gtq': total_liquido_gtq,
        'total_liquido_usd': round(total_liquido_gtq / tipo_cambio, 2) if es_dolares else None
    }